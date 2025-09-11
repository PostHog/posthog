import re
import json
import asyncio
import subprocess
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from django.core.management.base import BaseCommand

import aiohttp
import structlog

OUTPUT_FILE = "posthog/models/channel_type/channel_definitions.json"

VALID_ENTRY_RE = re.compile(r"^[ a-z0-9.+_-]+$")
logger = structlog.get_logger(__name__)

# when we search for apps we use .well-known files, but companies usually include their dev apps in that list, so use this list to try to filter them out
DEV_APP_STRINGS = [
    "dev",
    "staging",
    "stage",
    "qa",
    "internal",
    "feedback",
    "inhouse",
    "debug",
    "beta",
    "alpha",
    "gamma",
    "dogfood",
    "fishfood",
    "teamfood",
    "sample",
    "canary",
    "test",
    "prototype",
    "preview",
    "releasecandidate",
    "nightly",
]


class EntryKind(StrEnum):
    source = "source"
    medium = "medium"


@dataclass()
class SourceEntry:
    hostname_type: Optional[str]
    type_if_paid: Optional[str]
    type_if_organic: Optional[str]
    is_reverse_dns: Optional[bool] = False


class Command(BaseCommand):
    help = (
        "Write the channel_definitions.json file. Needs a ga4 sources file like"
        "https://storage.googleapis.com/support-kms-prod/qn1xhBu8MVcZPIZ2WZMNdI40FtZXFPGYxj2K"
        "as input. The best way I have found to do this is to open it in Google Docs, then save it as a text file. "
        "According the Google, they review this doc 'at least once a year and often more frequently', see "
        "https://support.google.com/analytics/answer/9756891"
    )

    def add_arguments(self, parser):
        parser.add_argument("ga_sources", type=str, help="GA Sources Input file")

    def handle(self, *args, **options):
        # start with previous channel definitions file:
        with open(OUTPUT_FILE) as output_file:
            existing_channel_definitions_json = json.loads(output_file.read())

        entries: OrderedDict[tuple[str, str], SourceEntry] = OrderedDict(
            (
                (existing_channel_definition[0], EntryKind(existing_channel_definition[1])),
                SourceEntry(
                    hostname_type=existing_channel_definition[2],
                    type_if_paid=existing_channel_definition[3],
                    type_if_organic=existing_channel_definition[4],
                    is_reverse_dns=existing_channel_definition[5],
                ),
            )
            for existing_channel_definition in existing_channel_definitions_json
        )

        input_arg = options.get("ga_sources")
        if not input_arg:
            raise ValueError("No input file specified")
        with open(input_arg, encoding="utf-8-sig") as input_file:
            input_str = input_file.read()
        split_items = re.findall(r"\S+\s+SOURCE_CATEGORY_\S+", input_str)

        types = {
            "SOURCE_CATEGORY_SEARCH": ("Search", "Paid Search", "Organic Search"),
            "SOURCE_CATEGORY_SHOPPING": ("Shopping", "Paid Shopping", "Organic Shopping"),
            "SOURCE_CATEGORY_SOCIAL": ("Social", "Paid Social", "Organic Social"),
            "SOURCE_CATEGORY_VIDEO": ("Video", "Paid Video", "Organic Video"),
        }

        for entry in split_items:
            items = re.findall(r"\S+", entry.strip())
            if len(items) != 2:
                return None
            domain, raw_type = items
            base_type, type_if_paid, type_if_organic = types[raw_type]
            entries[(domain, EntryKind.source)] = SourceEntry(base_type, type_if_paid, type_if_organic)

        # add google domains to this, from https://www.google.com/supported_domains
        for google_domain in [
            *".google.com .google.ad .google.ae .google.com.af .google.com.ag .google.al .google.am .google.co.ao "
            ".google.com.ar .google.as .google.at .google.com.au .google.az .google.ba .google.com.bd .google.be "
            ".google.bf .google.bg .google.com.bh .google.bi .google.bj .google.com.bn .google.com.bo "
            ".google.com.br .google.bs .google.bt .google.co.bw .google.by .google.com.bz .google.ca .google.cd "
            ".google.cf .google.cg .google.ch .google.ci .google.co.ck .google.cl .google.cm .google.cn "
            ".google.com.co .google.co.cr .google.com.cu .google.cv .google.com.cy .google.cz .google.de .google.dj "
            ".google.dk .google.dm .google.com.do .google.dz .google.com.ec .google.ee .google.com.eg .google.es "
            ".google.com.et .google.fi .google.com.fj .google.fm .google.fr .google.ga .google.ge .google.gg "
            ".google.com.gh .google.com.gi .google.gl .google.gm .google.gr .google.com.gt .google.gy "
            ".google.com.hk .google.hn .google.hr .google.ht .google.hu .google.co.id .google.ie .google.co.il "
            ".google.im .google.co.in .google.iq .google.is .google.it .google.je .google.com.jm .google.jo "
            ".google.co.jp .google.co.ke .google.com.kh .google.ki .google.kg .google.co.kr .google.com.kw "
            ".google.kz .google.la .google.com.lb .google.li .google.lk .google.co.ls .google.lt .google.lu "
            ".google.lv .google.com.ly .google.co.ma .google.md .google.me .google.mg .google.mk .google.ml "
            ".google.com.mm .google.mn .google.com.mt .google.mu .google.mv .google.mw .google.com.mx "
            ".google.com.my .google.co.mz .google.com.na .google.com.ng .google.com.ni .google.ne .google.nl "
            ".google.no .google.com.np .google.nr .google.nu .google.co.nz .google.com.om .google.com.pa "
            ".google.com.pe .google.com.pg .google.com.ph .google.com.pk .google.pl .google.pn .google.com.pr "
            ".google.ps .google.pt .google.com.py .google.com.qa .google.ro .google.ru .google.rw .google.com.sa "
            ".google.com.sb .google.sc .google.se .google.com.sg .google.sh .google.si .google.sk .google.com.sl "
            ".google.sn .google.so .google.sm .google.sr .google.st .google.com.sv .google.td .google.tg "
            ".google.co.th .google.com.tj .google.tl .google.tm .google.tn .google.to .google.com.tr .google.tt "
            ".google.com.tw .google.co.tz .google.com.ua .google.co.ug .google.co.uk .google.com.uy .google.co.uz "
            ".google.com.vc .google.co.ve .google.co.vi .google.com.vn .google.vu .google.ws .google.rs "
            ".google.co.za .google.co.zm .google.co.zw .google.cat".split(" "),
            "google",
        ]:
            google_domain = google_domain.strip()
            if google_domain[0] == ".":
                google_domain = google_domain[1:]
            if not google_domain:
                continue
            entries[(google_domain, EntryKind.source)] = SourceEntry("Search", "Paid Search", "Organic Search")

        # add bing domains to this, selectively picked from
        # https://github.com/v2fly/domain-list-community/blob/master/data/bing
        for bing_domain in ("bing.com", "bing.com.cn", "bing.net", "bingworld.com"):
            entries[(bing_domain, EntryKind.source)] = SourceEntry("Search", "Paid Search", "Organic Search")

        # The Google-provided list is missing some other search engines, or miss some subdomains, so add them here
        for search_domain in (
            # from https://en.wikipedia.org/wiki/List_of_search_engines
            "www.ask.com",
            "search.brave.com",
            "www.baidu.com",
            "www.dogpile.com",
            "duckduckgo.com",
            "www.ecosia.org",
            "www.excite.com",
            "www.gigablast.com",
            # Google domains included above
            "www.hotbot.com",
            "kagi.com",
            "www.lycos.com",
            "www.metacrawler.com",
            # Microsoft Bing domains included above
            "www.mojeek.com",
            "www.qwant.com",
            "www.sogou.com",
            "www.startpage.com",
            "swisscows.com",
            "www.webcrawler.com",
            # Yahoo already included
            # Yandex already included
            "you.com",
            # some other popular search engines and search engines used by our customers' users
            "www.kiddle.co",
            "www.egerin.com",
            "presearch.io",
            "presearch.com",
            "perplexity.ai",
            "m.search.naver.com",
            "yep.com",
            "andisearch.com",
            "phind.com",
            "komo.ai",
            "sevasearch.org",
            "coccoc.com",
            "so.com",
            "seznam.cz",
            "www.onesearch.com",
            "www.searchlock.com",
            "crowdsearch.net",
            "tusksearch.com",
            "search.lilo.org",
            "www.juniorsafesearch.com",
            "my-web-search.com",
            "search.xyz",
            "www.junosearch.net",
            "search.aol.com",
            "www.kidzsearch.com",
            "directsearch.io",
            "search-results-now.com"
            # this showed up for some customers and after some head scratching, rot13(tbbtyf) = googls
            # I also googled this and most of the results were people asking what this was
            "tbbtyf",
        ):
            entries[(search_domain, EntryKind.source)] = SourceEntry("Search", "Paid Search", "Organic Search")

        # add social domains
        for social_domain in (
            "bsky.app",
            # we're never going to include all mastodon instances, but grab a few popular ones and a few tech ones
            "mastodon.social",
            "mstdn.jp",
            "mastodon.cloud",
            "mastodon.world",
            "mstdn.social",
            "mastodon.online",
            "fosstodon.org",
            "techhub.social",
            "infosec.exchange",
            "hachyderm.io",
            "masto.ai",
            # threads
            "www.threads.net",
            # telegram
            "web.telegram.org",
            "t.me",
            # discord
            "discord.com",
            "discordapp.gg",
            # twitter
            "twitter.com",
            "t.co",
            "x.com",
        ):
            entries[(social_domain, EntryKind.source)] = SourceEntry("Social", "Paid Social", "Organic Social")

        for email_domain in (
            "outlook.live.com",
            "mail.google.com",
            "mail.yahoo.com",
            "mail.aol.com",
            "mail.aol.co.uk",
            "mail.proton.me",
        ):
            entries[(email_domain, EntryKind.source)] = SourceEntry("Email", None, "Email")

        # add other sources
        for email_spelling in ("email", "e-mail", "e_mail", "e mail"):
            entries[email_spelling, EntryKind.source] = SourceEntry(None, None, "Email")
            entries[email_spelling, EntryKind.medium] = SourceEntry(None, None, "Email")
        entries["firebase", EntryKind.source] = SourceEntry(None, None, "Push")
        entries["sms", EntryKind.source] = SourceEntry(None, None, "SMS")

        # add mediums
        for display_medium in ("display", "banner", "expandable", "interstitial", "cpm"):
            entries[display_medium, EntryKind.medium] = SourceEntry(None, "Display", "Display")
        for social_medium in ("social", "social-network", "social-media", "sm", "social network", "social media"):
            entries[social_medium, EntryKind.medium] = SourceEntry(None, "Paid Social", "Organic Social")
        for video_medium in ("video",):
            entries[video_medium, EntryKind.medium] = SourceEntry(None, "Paid Video", "Organic Video")
        for referral_medium in ("referral", "app", "link"):
            entries[referral_medium, EntryKind.medium] = SourceEntry(None, None, "Referral")
        for affiliate_medium in ("affiliate", "partnership", "partnerships"):
            entries[affiliate_medium, EntryKind.medium] = SourceEntry(None, None, "Affiliate")
        for audio_medium in ("audio",):
            entries[audio_medium, EntryKind.medium] = SourceEntry(None, None, "Audio")
        for push_medium in ("push", "mobile", "notification"):
            entries[push_medium, EntryKind.medium] = SourceEntry(None, None, "Push")

        # find mobile apps and add their bundle / app ids by looking for .well-known files on those domains
        potential_app_domains = [
            (domain, entry)
            for ((domain, kind), entry) in entries.items()
            if domain and kind == EntryKind.source and entry.hostname_type and "google" not in domain
        ]
        apple_apps = asyncio.run(parallel_lookup_up_apple_apps(potential_app_domains))
        android_apps = asyncio.run(parallel_lookup_up_android_apps(potential_app_domains))

        for record in apple_apps + android_apps:
            if not record:
                continue
            app_ids, entry = record
            for app_id in app_ids:
                # try to filter dev apps, if we exclude something that we want to keep, we can explicitly add it below
                if any(s in app_id for s in DEV_APP_STRINGS):
                    continue

                # google apps are a bit tricky so we have some special code to handle them
                if app_id.startswith("com.google."):
                    if "youtube" in app_id:
                        entries[app_id, EntryKind.source] = SourceEntry(
                            hostname_type="Video",
                            type_if_organic="Organic Video",
                            type_if_paid="Paid Video",
                            is_reverse_dns=True,
                        )
                    elif any(x in app_id for x in ("spaces", "photos")):
                        entries[app_id, EntryKind.source] = SourceEntry(
                            hostname_type="Social",
                            type_if_organic="Organic Social",
                            type_if_paid="Paid Social",
                            is_reverse_dns=True,
                        )
                    else:
                        continue
                # facebook have a ton of apps, many are not relevant
                elif app_id.startswith("com.facebook."):
                    if any(s in app_id for s in ("appmanager", "admin", "pageadminapp")):
                        continue
                elif app_id.startswith("com.microsoft.bing"):
                    # there's a ton of bing variants, only keep the original
                    if app_id != "com.microsoft.bing":
                        continue

                entries[app_id, EntryKind.source] = SourceEntry(
                    hostname_type=entry.hostname_type,
                    type_if_organic=entry.type_if_organic,
                    type_if_paid=entry.type_if_paid,
                    is_reverse_dns=True,
                )

        # add some well-known mobile apps
        # - google play: find package ids with the play store search
        # - ios: find bundle ids with https://offcornerdev.com/bundleid.html
        for app in (
            # linkedin
            "com.linkedin.android",
            "com.linkedin.LinkedIn",
            # reddit
            "com.reddit.frontpage",
            "com.reddit.reddit",
            # tiktok
            "com.zhiliaoapp.musically",
            # facebook
            "com.facebook.katana",
            "com.facebook.facebook",
            "com.facebook.messenger",
            # instagram
            "com.instagram.android",
            "com.burbn.instagram",
            # snapchat
            "com.snapchat.android",
            "com.toyopagroup.picaboo",
            # bluesky
            "xyz.blueskyweb.app",
            # twitter
            "com.twitter.android",
            "com.atebits.tweetie2",
            # mastodon
            "org.joinmastodon.android",
            # discord
            "com.hammerandchisel.discord",
            "com.discord",
            # deviant art - contains the "dev" string so excluded by our search above
            "com.deviantart.android.damobile",
            "com.deviantart.deviantart",
            # yahoo
            "com.yahoo.mobile.client.android.flickr",
            "com.flickr.android",
            "com.yahoo.mobile.client.android.fantasyfootball",
            # telegram
            "org.telegram.messenger",
            "org.telegram.messenger.web",
            "ph.telegra.Telegraph",
        ):
            entries[app.lower(), EntryKind.source] = SourceEntry(
                "Social", "Paid Social", "Organic Social", is_reverse_dns=True
            )
        for app in (
            # twitch
            "tv.twitch",
            "tv.twitch.android.app",
            # youtube
            "com.google.android.youtube",
            "com.google.ios.youtube",
            "com.google.ios.youtubekids",
            "com.google.android.apps.youtube.kids",
            "com.google.ios.youtubeunplugged",
            "com.google.android.youtube.tv",
        ):
            entries[app.lower(), EntryKind.source] = SourceEntry(
                "Video", "Paid Video", "Organic Video", is_reverse_dns=True
            )
        for app in (
            # android search widget
            "com.google.android.googlequicksearchbox",
            # yahoo
            "com.yahoo.apps.yahooapp",
            "com.yahoo.mobile.client.android.yahoo",
            "com.yahoo.www.twa",
            "com.yahoo.frontpage" "com.yahoo.weather",
        ):
            entries[app.lower(), EntryKind.source] = SourceEntry(
                "Search", "Paid Search", "Organic Search", is_reverse_dns=True
            )

        for app in (
            # apple
            "com.apple.mobilemail",
            # gmail
            "com.google.android.gm",
            "com.google.android.gm.lite",
            "com.google.Gmail",
            # superhuman
            "com.superhuman.mail",
            "com.superhuman.Superhuman",
            # outlook
            "com.microsoft.office.outlook",
            "com.microsoft.outlooklite",
            "com.microsoft.Office.Outlook",
            # yahoo
            "com.yahoo.mobile.client.android.mail",
            "com.yahoo.Aerogram",
            # samsung
            "com.samsung.android.email.provider",
            # edison
            "com.easilydo.mail",
            # protonmail
            "ch.protonmail.android",
            "ch.protonmail.protonmail",
            # bluemail
            "me.bluemail.mail",
            # aqua
            "org.kman.AquaMail",
            # aol
            "com.aol.mobile.aolapp",
            # mail.ru
            "ru.mail.mailapp",
            "ru.mail.mail",
            # yandex
            "ru.yandex.mail",
            # spike
            "com.pingapp.app",
            "com.readdle.smartemail",
        ):
            entries[app.lower(), EntryKind.source] = SourceEntry("Email", None, "Email", is_reverse_dns=True)

        # add without www. for all entries
        without_www = {
            (hostname[4:], kind): entry for ((hostname, kind), entry) in entries.items() if hostname.startswith("www.")
        }
        entries.update(without_www)

        rows = [
            (
                hostname,
                kind,
                entry.hostname_type,
                entry.type_if_paid,
                entry.type_if_organic,
                entry.is_reverse_dns,
            )
            for (hostname, kind), entry in entries.items()
            if (VALID_ENTRY_RE.match(hostname))
        ]

        # sort entries by fld where possible
        from tld import get_fld
        from tld.utils import update_tld_names

        update_tld_names()

        def sort_key(row):
            name, kind, hostname_type, type_if_paid, type_if_organic, is_reverse_dns = row
            if name and is_reverse_dns:
                source_fld = get_fld(str.join(".", reversed(name.split("."))), fail_silently=True, fix_protocol=True)
            else:
                source_fld = get_fld(name, fail_silently=True, fix_protocol=True)
            return [kind, source_fld or name, name]

        rows = sorted(rows, key=sort_key)

        # write a pretty JSON file out
        with open(OUTPUT_FILE, "w") as output_file:
            output_file.write(json.dumps(rows))
        subprocess.run(["npx", "--no-install", "prettier", "--write", OUTPUT_FILE])


async def parallel_lookup_up_apple_apps(url_entries):
    async def f(domain_entry, session):
        (domain, entry) = domain_entry
        url = f"https://{domain}/.well-known/apple-app-site-association"
        try:
            async with session.get(url=url) as response:
                text = await response.read()
                body = json.loads(text)
        except:
            # If we get an error, ignore it. The domain might not have an applinks file, and may not even exist at all,
            # it just means that we won't be able to get any bundle ids from it.
            return
        app_ids = []
        if not isinstance(body, dict):
            return
        for app in body.get("applinks", {}).get("details", []):
            if not isinstance(app, dict):
                logger.info("Unexpected shape for app, expected dict", app)
                continue
            app_id = app.get("appID")
            try:
                if app_id:
                    bundle_id = app_id.split(".", 1)[1].lower()
                    if VALID_ENTRY_RE.match(bundle_id):
                        app_ids.append(bundle_id)
            except IndexError:
                logger.info("Failed to parse applinks appID", app_id)
                pass
        return app_ids, entry

    async with aiohttp.ClientSession(read_timeout=60, conn_timeout=60) as session:
        return await asyncio.gather(*(f(url_entry, session) for url_entry in url_entries))


async def parallel_lookup_up_android_apps(url_entries):
    async def f(domain_entry, session):
        (domain, entry) = domain_entry
        url = f"https://{domain}/.well-known/assetlinks.json"
        try:
            async with session.get(url=url) as response:
                text = await response.read()
                body = json.loads(text)
        except:
            # If we get an error, ignore it. The domain might not have an assetlinks file, and may not even exist at all,
            # it just means that we won't be able to get any package ids from it.
            return
        app_ids = []
        if not isinstance(body, list):
            return
        for app in body:
            package_name = app.get("target", {}).get("package_name")
            if package_name and isinstance(package_name, str):
                package_name = package_name.lower()
                app_ids.append(package_name)
        return app_ids, entry

    async with aiohttp.ClientSession(read_timeout=60, conn_timeout=60) as session:
        return await asyncio.gather(*(f(url_entry, session) for url_entry in url_entries))
