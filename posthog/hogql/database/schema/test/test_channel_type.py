import uuid
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from posthog.schema import CustomChannelCondition, CustomChannelRule, FilterLogicalOperator, HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.utils import uuid7


class TestReferringDomainType(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _get_initial_referring_domain_type(self, initial_referring_domain: str):
        person_id = str(uuid.uuid4())

        _create_person(
            uuid=person_id,
            team_id=self.team.pk,
            distinct_ids=[person_id],
            properties={
                "$initial_referring_domain": initial_referring_domain,
            },
        )

        response = execute_hogql_query(
            parse_select(
                "select $virt_initial_referring_domain_type as channel_type from persons where id = {person_id}",
                placeholders={"person_id": ast.Constant(value=person_id)},
            ),
            self.team,
        )

        return response.results[0][0]

    def test_direct(self):
        self.assertEqual(
            "$direct",
            self._get_initial_referring_domain_type("$direct"),
        )

    def test_search(self):
        self.assertEqual(
            "Search",
            self._get_initial_referring_domain_type("www.google.co.uk"),
        )
        self.assertEqual(
            "Search",
            self._get_initial_referring_domain_type("yahoo.co.jp"),
        )

    def test_shopping(self):
        self.assertEqual(
            "Shopping",
            self._get_initial_referring_domain_type("m.alibaba.com"),
        )
        self.assertEqual(
            "Shopping",
            self._get_initial_referring_domain_type("stripe.com"),
        )
        self.assertEqual("Shopping", self._get_initial_referring_domain_type("shopping.yahoo.co.jp"))

    def test_social(self):
        self.assertEqual(
            "Social",
            self._get_initial_referring_domain_type("lnkd.in"),
        )
        self.assertEqual(
            "Social",
            self._get_initial_referring_domain_type("old.reddit.com"),
        )
        self.assertEqual(
            "Social",
            self._get_initial_referring_domain_type("plus.google.com"),
        )
        self.assertEqual(
            "Social",
            self._get_initial_referring_domain_type("news.ycombinator.com"),
        )


class TestChannelType(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _get_person_initial_channel_type(self, properties=None):
        person_id = str(uuid.uuid4())

        _create_person(
            uuid=person_id,
            team_id=self.team.pk,
            distinct_ids=[person_id],
            properties=properties,
        )

        person_response = execute_hogql_query(
            parse_select(
                "select $virt_initial_channel_type as channel_type from persons where id = {person_id}",
                placeholders={"person_id": ast.Constant(value=person_id)},
            ),
            self.team,
        )
        return (person_response.results or [])[0][0]

    def _get_session_channel_type(self, properties=None, custom_channel_rules=None):
        person_id = str(uuid.uuid4())
        properties = {
            "$session_id": str(uuid7()),
            **(properties or {}),
        }
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=person_id,
            properties=properties,
        )
        session_response = execute_hogql_query(
            parse_select(
                "select events.session.$channel_type as channel_type, events.session.$entry_utm_source, events.session.$entry_utm_medium, events.session.$entry_utm_campaign, events.session.$entry_referring_domain from events where distinct_id = {person_id}",
                placeholders={"person_id": ast.Constant(value=person_id)},
            ),
            self.team,
            modifiers=HogQLQueryModifiers(customChannelTypeRules=custom_channel_rules),
        )
        return (session_response.results or [])[0][0]

    def test_direct(self):
        self.assertEqual(
            "Direct",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "$direct",
                }
            ),
        )

    def test_direct_empty_string(self):
        self.assertEqual(
            "Direct",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "$direct",
                    "$initial_utm_source": "",
                    "$initial_utm_medium": "",
                    "$initial_utm_campaign": "",
                    "$initial_gclid": "",
                    "$initial_gad_source": "",
                }
            ),
        )

    def test_direct_null_string(self):
        self.assertEqual(
            "Direct",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "$direct",
                    "$initial_utm_source": "null",
                    "$initial_utm_medium": "null",
                    "$initial_utm_campaign": "null",
                    "$initial_gclid": "null",
                    "$initial_gad_source": "null",
                }
            ),
        )

    def test_cross_network(self):
        self.assertEqual(
            "Cross Network",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "$direct",
                    "$initial_utm_campaign": "cross-network",
                }
            ),
        )

    def test_paid_shopping_domain(self):
        self.assertEqual(
            "Paid Shopping",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "www.ebay.co.uk",
                    "$initial_utm_medium": "ppc",
                }
            ),
        )

    def test_paid_shopping_source(self):
        self.assertEqual(
            "Paid Shopping",
            self._get_person_initial_channel_type(
                {
                    "$initial_utm_source": "ebay",
                    "$initial_utm_medium": "ppc",
                }
            ),
        )

    def test_paid_shopping_campaign(self):
        self.assertEqual(
            "Paid Shopping",
            self._get_person_initial_channel_type(
                {
                    "$initial_utm_campaign": "shopping",
                    "$initial_utm_medium": "ppc",
                }
            ),
        )

    def test_paid_search(self):
        self.assertEqual(
            "Paid Search",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "www.google.co.uk",
                    "$initial_gclid": "some-gclid",
                }
            ),
        )

    def test_paid_search_source(self):
        self.assertEqual(
            "Paid Search",
            self._get_person_initial_channel_type(
                {
                    "$initial_utm_source": "yahoo",
                    "$initial_utm_medium": "ppc",
                }
            ),
        )

    def test_paid_video(self):
        self.assertEqual(
            "Paid Video",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "youtube.com",
                    "$initial_utm_medium": "cpc",
                }
            ),
        )

    def test_paid_video_source(self):
        self.assertEqual(
            "Paid Video",
            self._get_person_initial_channel_type(
                {
                    "$initial_utm_source": "youtube.com",
                    "$initial_utm_medium": "cpc",
                }
            ),
        )

    def test_organic_video(self):
        self.assertEqual(
            "Organic Video",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "youtube.com",
                }
            ),
        )

    def test_direct_with_red_herring_utm_tags_is_direct(self):
        self.assertEqual(
            "Direct",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "$direct",
                    "$initial_utm_source": "what",
                    "$initial_utm_medium": "who",
                    "$initial_utm_campaign": "slim shady",
                }
            ),
        )

    def test_no_info_is_unknown(self):
        self.assertEqual(
            "Unknown",
            self._get_person_initial_channel_type({}),
        )

    def test_unknown_domain_is_referral(self):
        self.assertEqual(
            "Referral",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "some-unknown-domain.example.com",
                }
            ),
        )

    def test_doesnt_fail_on_numbers(self):
        self.assertEqual(
            "Referral",
            self._get_person_initial_channel_type(
                {
                    "$initial_referring_domain": "example.com",
                    "$initial_utm_source": 123,
                    "$initial_utm_medium": 123,
                    "$initial_utm_campaign": 123,
                }
            ),
        )

    def test_empty_session(self):
        self.assertEqual(
            "Unknown",
            self._get_session_channel_type({}),
        )

    def test_empty_string_session(self):
        self.assertEqual(
            "Unknown",
            self._get_session_channel_type(
                {
                    "utm_source": "",
                    "utm_medium": "",
                    "utm_campaign": "",
                    "referring_domain": "",
                    "gclid": "",
                    "gad_source": "",
                }
            ),
        )

    def test_custom_channel_type(self):
        # add a custom channel type for a specific utm_source
        assert (
            self._get_session_channel_type(
                {
                    "utm_source": "test",
                },
                custom_channel_rules=[
                    CustomChannelRule(
                        items=[CustomChannelCondition(key="utm_source", op="exact", value="test", id="1")],
                        channel_type="Test",
                        combiner=FilterLogicalOperator.AND_,
                        id="a",
                    )
                ],
            )
            == "Test"
        )
        # add an array of values
        assert (
            self._get_session_channel_type(
                {
                    "utm_source": "test",
                },
                custom_channel_rules=[
                    CustomChannelRule(
                        items=[CustomChannelCondition(key="utm_source", op="exact", value=["test", "test2"], id="1")],
                        channel_type="Test",
                        combiner=FilterLogicalOperator.AND_,
                        id="a",
                    )
                ],
            )
            == "Test"
        )
        # add an array of a single value
        assert (
            self._get_session_channel_type(
                {
                    "utm_source": "test",
                },
                custom_channel_rules=[
                    CustomChannelRule(
                        items=[CustomChannelCondition(key="utm_source", op="exact", value=["test"], id="1")],
                        channel_type="Test",
                        combiner=FilterLogicalOperator.AND_,
                        id="a",
                    )
                ],
            )
            == "Test"
        )
        # add an array of conditions
        assert (
            self._get_session_channel_type(
                {
                    "utm_source": "s",
                    "utm_medium": "m",
                },
                custom_channel_rules=[
                    CustomChannelRule(
                        items=[
                            CustomChannelCondition(key="utm_source", op="exact", value="s", id="1"),
                            CustomChannelCondition(key="utm_medium", op="exact", value="m", id="2"),
                        ],
                        channel_type="Test",
                        combiner=FilterLogicalOperator.AND_,
                        id="a",
                    )
                ],
            )
            == "Test"
        )
        # add an array of rules
        assert (
            self._get_session_channel_type(
                {
                    "utm_source": "2",
                },
                custom_channel_rules=[
                    CustomChannelRule(
                        items=[CustomChannelCondition(key="utm_source", op="exact", value="1", id="1")],
                        channel_type="Test1",
                        combiner=FilterLogicalOperator.AND_,
                        id="a",
                    ),
                    CustomChannelRule(
                        items=[CustomChannelCondition(key="utm_source", op="exact", value="2", id="2")],
                        channel_type="Test2",
                        combiner=FilterLogicalOperator.AND_,
                        id="b",
                    ),
                ],
            )
            == "Test2"
        )
        # custom channel type using pathname
        assert (
            self._get_session_channel_type(
                {
                    "$current_url": "https://www.google.com/some/path",
                },
                custom_channel_rules=[
                    CustomChannelRule(
                        items=[CustomChannelCondition(key="pathname", op="exact", value="/some/path", id="1")],
                        channel_type="Test",
                        combiner=FilterLogicalOperator.AND_,
                        id="a",
                    ),
                ],
            )
            == "Test"
        )
        # custom channel type using hostname
        assert (
            self._get_session_channel_type(
                {
                    "$current_url": "https://google.com/some/path",
                },
                custom_channel_rules=[
                    CustomChannelRule(
                        items=[CustomChannelCondition(key="hostname", op="exact", value="google.com", id="1")],
                        channel_type="Test",
                        combiner=FilterLogicalOperator.AND_,
                        id="a",
                    ),
                ],
            )
            == "Test"
        )
        # custom channel type using hostname with port
        assert (
            self._get_session_channel_type(
                {
                    "$current_url": "https://google.com:3000/some/path",
                },
                custom_channel_rules=[
                    CustomChannelRule(
                        items=[CustomChannelCondition(key="hostname", op="exact", value="google.com", id="1")],
                        channel_type="Test",
                        combiner=FilterLogicalOperator.AND_,
                        id="a",
                    ),
                ],
            )
            == "Test"
        )
        # custom channel type using url
        assert (
            self._get_session_channel_type(
                {
                    "$current_url": "https://www.google.com/some/path",
                },
                custom_channel_rules=[
                    CustomChannelRule(
                        items=[CustomChannelCondition(key="url", op="icontains", value="/some/path", id="1")],
                        channel_type="Test",
                        combiner=FilterLogicalOperator.AND_,
                        id="a",
                    ),
                ],
            )
            == "Test"
        )

    def _get_initial_channel_type_from_wild_clicks(self, url: str, referrer: str):
        session_id = str(uuid7())
        parsed_url = urlparse(url)
        query = parse_qs(parsed_url.query)
        person_properties = {}
        event_properties = {
            "$session_id": session_id,
        }
        if utm_source := query.get("utm_source"):
            person_properties["$initial_utm_source"] = utm_source[0]
            event_properties["utm_source"] = utm_source[0]
        if utm_medium := query.get("utm_medium"):
            person_properties["$initial_utm_medium"] = utm_medium[0]
            event_properties["utm_medium"] = utm_medium[0]
        if utm_campaign := query.get("utm_campaign"):
            person_properties["$initial_utm_campaign"] = utm_campaign[0]
            event_properties["utm_campaign"] = utm_campaign[0]
        if gclid := query.get("gclid"):
            person_properties["$initial_gclid"] = gclid[0]
            event_properties["gclid"] = gclid[0]
        if gad_source := query.get("gad_source"):
            person_properties["$initial_gad_source"] = gad_source[0]
            event_properties["gad_source"] = gad_source[0]
        if msclickid := query.get("msclkid"):
            person_properties["$initial_msclkid"] = msclickid[0]
            event_properties["msclkid"] = msclickid[0]
        if fbclid := query.get("fbclid"):
            person_properties["$initial_fbclid"] = fbclid[0]
            event_properties["fbclid"] = fbclid[0]
        referring_domain = urlparse(referrer).netloc if referrer else "$direct"
        person_properties["$initial_referring_domain"] = referring_domain
        event_properties["$referring_domain"] = referring_domain

        session_channel_type = self._get_session_channel_type(event_properties)
        person_channel_type = self._get_person_initial_channel_type(person_properties)
        self.assertEqual(session_channel_type, person_channel_type)
        return person_channel_type

    def test_yahoo_search_for_shoes(self):
        # yahoo search for shoes -> click ad
        self.assertEqual(
            "Paid Search",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.temu.com/subject/n9/googleshopping-landingpage-a-psurl.html?_bg_fs=1&_p_rfs=1&_x_ads_sub_channel=shopping&_x_vst_scene=adg&mkt_rec=1&goods_id=601099512027500&sku_id=17592188550581&_x_ns_sku_id=17592188550581&_x_ads_channel=bing&_x_gmc_account=3429411&_x_gmc_catalog=1080172&_x_ads_creative_id=82326302656241&_x_ns_device=c&_x_ads_account=176202708&_x_ns_match_type=e&_x_ns_msclkid=98833ce81fa416f104e8599a17a48b7d&_x_ads_set=519351414&_x_ns_source=o&_x_ads_id=1317217234030436&msclkid=98833ce81fa416f104e8599a17a48b7d&utm_source=bing&utm_medium=cpc&utm_campaign=Bing%E8%B4%AD%E7%89%A9_GB_ROI_31148%E6%88%B7%E5%A4%96%E8%BF%90%E5%8A%A8_%E5%85%9C%E5%BA%95_%E9%80%9A%E6%8A%95_CHERIE_0812&utm_term=4585925565374752&utm_content=Bing%E8%B4%AD%E7%89%A9_GB_ROI_31148%E6%88%B7%E5%A4%96%E8%BF%90%E5%8A%A8_%E5%85%9C%E5%BA%95_%E9%80%9A%E6%8A%95_CHERIE_0812_2&adg_ctx=f-939d4ecb",
                "https://uk.search.yahoo.com/",
            ),
        )

    def test_chrome_google_search_for_shoes(self):
        # chrome google search for shoes -> click ad
        self.assertEqual(
            "Paid Search",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.vivaia.com/item/square-toe-v-cut-flats-p_10003645.html?gid=10011676&currency=GBP&shipping_country_code=GB&gad_source=1&gclid=CjwKCAiA98WrBhAYEiwA2WvhOuiyZpOvzXUVBP0KNplo9EFUSYmm4-gaxt_nFGB4knYLxi-l909iYxoC3OsQAvD_BwE",
                "",
            ),
        )

    def test_firefox_google_search_for_shoes(self):
        # firefox google search for shoes -> click ad
        self.assertEqual(
            "Paid Search",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.allbirds.co.uk/products/mens-wool-runner-mizzles-deep-emerald?gad_source=1&size=uk-7&utm_campaign=PMax%20%2F%2F%20UK%20%2F%2F%20Lifestyle%20Shoes&utm_content=&utm_medium=pmax&utm_source=google&utm_term=",
                "",
            ),
        )

    def test_daily_mail_ad_click(self):
        # go to daily mail -> click ad
        self.assertEqual(
            "Paid Unknown",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.vivaia.com/item/square-toe-v-cut-flats-p_10003645.html?gid=10011676&currency=GBP&shipping_country_code=GB&gclid=EAIaIQobChMIxvGy5rr_ggMVYi0GAB0KSAumEAEYASABEgLZ2PD_BwE",
                "https://2bb5cd7f10ba63d8b55ecfac1a3948db.safeframe.googlesyndication.com/",
            ),
        )

    def test_google_organic(self):
        # firefox or chrome
        # go to google -> click organic result
        self.assertEqual(
            "Organic Search",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.office.co.uk/",
                "https://www.google.com/",
            ),
        )

    def test_youtube_organic(self):
        # firefox
        # go to youtube -> click someone's twitter link in a video description
        self.assertEqual(
            "Organic Video",
            self._get_initial_channel_type_from_wild_clicks(
                "https://twitter.com/hbomberguy",
                "https://www.youtube.com/",
            ),
        )

    def test_youtube_sidebar_ad(self):
        # chrome
        # go to youtube -> click an ad in the sidebar
        self.assertEqual(
            "Paid Video",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.quooker.co.uk/?gclid=CjwKCAiAmsurBhBvEiwA6e-WPNVcMzaGnrW8G2Wd4Ye-dB5GZMPxohf-_sJRqThISXVzS97mq4s2MBoCK_wQAvD_BwE",
                "https://www.youtube.com/",
            ),
        )

    def test_youtube_video_ad(self):
        # chrome
        # go to youtube -> click an ad in the video
        self.assertEqual(
            "Paid Video",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.quooker.co.uk/?gclid=CjwKCAiAmsurBhBvEiwA6e-WPNVcMzaGnrW8G2Wd4Ye-dB5GZMPxohf-_sJRqThISXVzS97mq4s2MBoCK_wQAvD_BwE",
                "https://www.youtube.com/",
            ),
        )

    def test_facebook_sidebar_ad(self):
        # chrome
        # go to facebook -> click an ad in the sidebar
        self.assertEqual(
            "Paid Social",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.tothefairest.com/shop/?utm_source=facebook&utm_medium=cpc&utm_campaign=120201466136570051&fbclid=IwAR30EpkagUJ3vLo7_tl0R8FjnA3vnm5d6jzHvjwhNCm4kXDsAmTfDsckJBc",
                "https://l.facebook.com/",
            ),
        )

    def test_facebook_feed_ad(self):
        # chrome
        # go to facebook -> click an ad in the feed
        self.assertEqual(
            "Paid Social",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.loopearplugs.com/products/switch?utm_source=facebook&utm_medium=paid&utm_campaign=UK_EN_TOF_Purchase_BAU_ABO_NoScale_19.05.23&utm_content=UK_EN_TOF-Fashion-Interest-TOF_AllPlacements_AllGenders_18-65%2B_Carouselimage-Mix-3in1-v2_carousel-image_Question-overstimulation-v1_All_Purchase_LP-Switch_Highest-Value_BAU_Switch_NA&utm_term=120201603163080541&fbclid=IwAR3KhttbYqH0GWskV5LGQKXnPKmHwaKdW8gvHbEPHR5IYX8GDf2hhxAslso",
                "https://l.facebook.com/",
            ),
        )

    def test_facebook_feed_organic_link(self):
        # chrome
        # go to facebook -> click a link in the feed
        self.assertEqual(
            "Organic Social",
            self._get_initial_channel_type_from_wild_clicks(
                "https://lifehacker.com/get-two-of-obsidian-entertainments-best-pc-rpgs-for-fre-1845845998?fbclid=IwAR1ZEOUVr76FRjZWnIio-v0gl5WWvd8soknOd6W6h580Grk34-Jpl1ai-kU",
                "https://l.facebook.com/",
            ),
        )

    def test_bing_ad_click(self):
        # go to bing -> search shoes -> click an ad
        # chrome
        self.assertEqual(
            "Paid Search",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.mrporter.com/en-gb/mens/product/brunello-cucinelli/shoes/espadrilles/suede-espadrilles/1647597324114522?cm_mmc=sea&vtp00=BING&vtp01=SEAU&vtp02=483499616&vtp03=1239150613976957&vtp04=&vtp05=&vtp06=pla-4581046492826348&vtp07=&vtp08=&vtp09=e&vtp10=o&vtp11=c&vtp12=77447044368184&vtp13=shoes&vtp14=&vtp15=MR%20PORTER&vtp16=0400639982683&vtp17=GB&vtp18=EN&vtp19=4581046492826348&msclkid=f72b49e2bf2719cb4ee22c91ac4963a7&utm_source=bing&utm_medium=cpc&utm_campaign=BNG%3AMRP%3AEU%3AGB%3ALO%3AENG%3ASEAU%3APLA%3ASLR%3AMXO%3ANEW%3AMN%3ABRUNELLO-CUCINELLI%3ALV0%3ALV1%3ALV2%3AXXX%3A14%3AEMPTY%3A&utm_term=4581046492826348&utm_content=GOO%3AMRP%3AEU%3AGB%3ALO%3AENG%3ASEAU%3APLA%3ASLR%3AMXO%3ANEW%3AMN%3ABRUNELLO-CUCINELLI%3ASHOES%3ASUEDE_SHOES%3ASUEDE_SHOES%3AXXX%3A14%3AEMPTY%3A",
                "https://www.bing.com/",
            ),
        )
        # in firefox
        self.assertEqual(
            "Paid Search",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.nisbets.co.uk/nisbets-essentials-chefs-clog-black-3839/b979-3839?vatToggle=incvat&plaid=1&cm_mmc=BingPLA-_-710225369-_-1246847484880804-_-B979-3839&cm_mmca1=bi_710225369_1246847484880804_77928093437482_pla-4581527532440033_c_&utm_id=bing_710225369_1246847484880804_77928093437482_pla-4581527532440033%3Apla-4581527532440033_c&kpid=bi_cmp-710225369_adg-1246847484880804_ad-77928093437482_pla-4581527532440033_dev-c_ext-_prd-B979-3839_sig-febaceddde9f13596573abaecd6840bc&utm_source=bing&utm_medium=cpc&utm_campaign=8+-+Shopping+-+Clothing&utm_term=4581527532440033&utm_content=Clothing",
                "",
            ),
        )

    def test_bing_organic_click(self):
        # go to bing -> search shoes -> click an organic result
        # chrome and firefox
        self.assertEqual(
            "Organic Search",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.schuh.co.uk/",
                "https://www.bing.com/",
            ),
        )

    def test_duckduckgo_organic_click(self):
        # go to duckduckgo -> search shoes -> click an organic result
        # firefox
        self.assertEqual(
            "Organic Search",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.asos.com/women/shoes/cat/?cid=4172",
                "https://duckduckgo.com/",
            ),
        )

    def test_duckduckgo_paid_click(self):
        # go to duckduckgo -> search shoes -> click an ad
        # chrome
        self.assertEqual(
            "Paid Search",
            self._get_initial_channel_type_from_wild_clicks(
                "https://www.temu.com/uk/kuiper/un2.html?_p_rfs=1&subj=un-search1&_p_jump_id=831&_x_vst_scene=adg&search_key=.%20shoes&_x_ads_sub_channel=search&_x_ads_channel=bing&_x_ads_account=176202190&_x_ads_set=519193183&_x_ads_id=1316117718217619&_x_ads_creative_id=82257583982288&_x_ns_source=s&_x_ns_msclkid=0c97748ea8581c0fa51611f9afccba18&_x_ns_match_type=e&_x_ns_bid_match_type=be&_x_ns_query=shoes&_x_ns_keyword=.%20shoes&_x_ns_device=c&_x_ns_targetid=kwd-82258273368290%3Aloc-188&_x_ns_extensionid=&msclkid=0c97748ea8581c0fa51611f9afccba18&utm_source=bing&utm_medium=cpc&utm_campaign=0725_WJJ_UK_KW_web-app-purchase-offline%7Cweb-purchase-offline_UK%E9%AB%98%E8%8A%B1%E8%B4%B9%E8%AF%8D9533&utm_term=.%20shoes&utm_content=0725_WJJ-%E9%80%9A%E6%8A%95-UK_UK_%E7%BB%9F%E4%B8%80%E6%90%9C%E7%B4%A2%E9%A1%B5%20%E3%80%90%E7%9B%B4%E6%8E%A5%E6%8A%95%E6%94%BE%E7%94%A8%E3%80%91_webtoapp_EXACT_UK%E9%AB%98%E8%8A%B1%E8%B4%B9%E8%AF%8D4977&adg_ctx=f-939d4ecb",
                "https://duckduckgo.com/",
            ),
        )

    def test_fbclid_only(self):
        # no reproduction, this just came from a support ticket, see https://posthoghelp.zendesk.com/agent/tickets/23328
        self.assertEqual(
            "Organic Social",
            self._get_initial_channel_type_from_wild_clicks(
                "https://xyz.com/?fbclid=ABC",
                "",
            ),
        )

    # # The one won't work, meta sites like instagram add fbclid regardless of whether it's an ad or not.
    # # Customers would need to add their own params to the url to work around this.
    # def test_instagram_feed_sponsored_link(self):
    #     # chrome
    #     # go to instagram -> click a link in the feed
    #     self.assertEqual(
    #         "Organic Social",
    #         self._get_initial_channel_type_from_wild_clicks(
    #             "https://www.shaktimat.co.uk/?utm_source=facebook&utm_medium=social&utm_campaign=UK+Remarketing+-+Conversions+-+Always+On&utm_content=9%2F11%2F23+-+Warm+-+Auto+-+263k&tw_source=ig&tw_adid=120202176962790544&fbclid=PAAaZjO5b3RD96GRWoaaRowR5wQBbQNHwGLJvuF1l-knOKk1UkatiHVRAdbLY_aem_AU95Wm2ImvJDO2jTWkfgbMIqGIcaCdVQh2po-OrtjExXqcULHjuuoUf_4_vPCuKh3DghZHcvWV8n8g-uwMrhte0O&campaign_id=120202176962760544&ad_id=120202176962790544",
    #             "https://shaktimat.com/",
    #         ),
    #     )

    # # The one won't work, linkedin doesn't add any params to the url that we can use.
    # # Customers would need to add their own params to the url to work around this.
    # def test_linkedin_feed_sponsored_link(self):
    #     # chrome
    #     # go to linkedin -> click a sponsored link in the feed
    #     self.assertEqual(
    #         "Paid Social",
    #         self._get_initial_channel_type_from_wild_clicks(
    #             "https://learning.central.xero.com/student/path/2667", "https://www.linkedin.com/"
    #         ),
    #     )

    # # This one won't work, as fcblid is not enough to know whether something is an ad or not.
    # # Customers would need to add their own params to the url to work around this.
    # def test_facebook_marketplace_ad(self):
    #     # chrome
    #     # go to facebook -> click an ad in the marketplace
    #     self.assertEqual(
    #         "Paid Social",
    #         self._get_initial_channel_type_from_wild_clicks(
    #             "https://mynextbike.co.uk/collections/road-bike?utm_source=facebook&utm_medium=social&utm_campaign=KC%20-%20AAA%20-%20Prospecting&utm_term=Road%20Cycling%20%E2%80%93%20Copy%202&utm_content=Image%20-%20Bike%20On%20Wall&cmc_adid=fb_120202383554070310&fbclid=IwAR30EpkagUJ3vLo7_tl0R8FjnA3vnm5d6jzHvjwhNCm4kXDsAmTfDsckJBc",
    #             "https://l.facebook.com/",
    #         ),
    #     )

    def test_zendesk_ticket_14945(self):
        # see https://posthoghelp.zendesk.com/agent/tickets/14945

        # In this ticket, a customer's paid social traffic was incorrect tagged as organic social, because we
        # didn't recognise the word "Paid" with an uppercase 'P' as a paid source. Really, this should have
        # been case-insensitive, and that is what the fix was.
        self.assertEqual(
            "Paid Social",
            self._get_session_channel_type(
                {
                    "utm_source": "Facebook",
                    "utm_medium": "Paid",
                    "utm_campaign": "Foo",
                    "referring_domain": "l.facebook.com",
                    "gclid": "",
                    "gad_source": "",
                }
            ),
        )

        # the customer also provided us with a list of urls that weren't attributing correctly, and we changed the
        # algorithm to give utm_medium priority over referring domain. This tests a few specific examples:
        assert (
            self._get_session_channel_type(
                {
                    "utm_source": "substack",
                    "utm_medium": "email",
                    "$referring_domain": "bing.com",
                }
            )
            == "Email"
        )
        assert (
            self._get_session_channel_type(
                {
                    "utm_source": "Foo",
                    "utm_medium": "affiliate",
                    "$referring_domain": "bing.com",
                }
            )
            == "Affiliate"
        )
        assert (
            self._get_session_channel_type(
                {
                    "utm_source": "Foo",
                    "utm_medium": "partnership",
                    "$referring_domain": "foo.com",
                }
            )
            == "Affiliate"
        )

    def test_hacker_news(self):
        # news.ycombinator.com is interesting because we don't have an entry for ycombinator.com, only the subdomain

        self.assertEqual(
            "Organic Social",
            self._get_session_channel_type(
                {
                    "utm_source": "",
                    "utm_medium": "in-product",
                    "utm_campaign": "empty-state-docs-link",
                    "$referring_domain": "news.ycombinator.com",
                    "gclid": "",
                    "gad_source": "",
                }
            ),
        )

        self.assertEqual(
            "Organic Social",
            self._get_session_channel_type(
                {
                    "utm_source": "news.ycombinator.com",
                    "utm_medium": "in-product",
                    "utm_campaign": "empty-state-docs-link",
                    "$referring_domain": "$direct",
                    "gclid": "",
                    "gad_source": "",
                }
            ),
        )

    def test_google_plus(self):
        # plus.google.com is interesting because it should be social, but just google.com is search
        assert (
            self._get_session_channel_type(
                {
                    "utm_source": "plus.google.com",
                    "$referring_domain": "$direct",
                }
            )
            == "Organic Social"
        )

        assert (
            self._get_session_channel_type(
                {
                    "$referring_domain": "plus.google.com",
                }
            )
            == "Organic Social"
        )

    def test_gmail_app(self):
        # plus.google.com is interesting because it should be social, but just google.com is search
        assert (
            self._get_session_channel_type(
                {
                    "$referring_domain": "com.google.android.gm",
                }
            )
            == "Email"
        )
