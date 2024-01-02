import json
import re
import subprocess
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from django.core.management.base import BaseCommand


OUTPUT_FILE = "posthog/models/channel_type/channel_definitions.json"


class EntryKind(str, Enum):
    source = "source"
    medium = "medium"


@dataclass()
class SourceEntry:
    hostname_type: Optional[str]
    type_if_paid: Optional[str]
    type_if_organic: Optional[str]


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
        input_arg = options.get("ga_sources")
        if not input_arg:
            raise ValueError("No input file specified")
        with open(input_arg, "r", encoding="utf-8-sig") as input_file:
            input_str = input_file.read()
        split_items = re.findall(r"\S+\s+SOURCE_CATEGORY_\S+", input_str)

        types = {
            "SOURCE_CATEGORY_SEARCH": ("Search", "Paid Search", "Organic Search"),
            "SOURCE_CATEGORY_SHOPPING": ("Shopping", "Paid Shopping", "Organic Shopping"),
            "SOURCE_CATEGORY_SOCIAL": ("Social", "Paid Social", "Organic Social"),
            "SOURCE_CATEGORY_VIDEO": ("Video", "Paid Video", "Organic Video"),
        }

        def handle_entry(entry):
            items = re.findall(r"\S+", entry.strip())
            if len(items) != 2:
                return None
            domain, raw_type = items
            base_type, type_if_paid, type_if_organic = types[raw_type]
            return (domain, EntryKind.source), SourceEntry(base_type, type_if_paid, type_if_organic)

        entries: OrderedDict[Tuple[str, str], SourceEntry] = OrderedDict(map(handle_entry, split_items))

        # add google domains to this, from https://www.google.com/supported_domains
        for google_domain in (
            ".google.com .google.ad .google.ae .google.com.af .google.com.ag .google.al .google.am .google.co.ao "
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
            ".google.co.za .google.co.zm .google.co.zw .google.cat"
        ).split(" ") + ["google"]:
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

        # misc other domains that GA4 misses
        entries["duckduckgo.com", EntryKind.source] = SourceEntry("Search", "Paid Search", "Organic Search")

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
        for affiliate_medium in ("affiliate",):
            entries[affiliate_medium, EntryKind.medium] = SourceEntry(None, None, "Affiliate")
        for audio_medium in ("audio",):
            entries[audio_medium, EntryKind.medium] = SourceEntry(None, None, "Audio")
        for push_medium in ("push", "mobile", "notification"):
            entries[push_medium, EntryKind.medium] = SourceEntry(None, None, "Push")

        rows = [
            [hostname, kind, entry.hostname_type, entry.type_if_paid, entry.type_if_organic]
            for (hostname, kind), entry in entries.items()
        ]

        # sort entries by fld where possible
        from tld import get_fld
        from tld.utils import update_tld_names

        update_tld_names()

        def sort_key(row):
            name, kind, hostname_type, type_if_paid, type_if_organic = row
            source_fld = get_fld(name, fail_silently=True, fix_protocol=True)
            return [kind, source_fld or name, name]

        rows = sorted(rows, key=sort_key)

        # write a pretty JSON file out
        with open(OUTPUT_FILE, "w") as output_file:
            output_file.write(json.dumps(rows))
        subprocess.run(["npx", "--no-install", "prettier", "--write", OUTPUT_FILE])
