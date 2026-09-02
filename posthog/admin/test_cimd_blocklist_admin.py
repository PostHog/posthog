from posthog.test.base import BaseTest

from django.contrib.admin import AdminSite
from django.core.cache import cache
from django.test import RequestFactory

from parameterized import parameterized

from posthog.admin.admins.cimd_blocklist_admin import CIMDBlocklistEntryAdmin
from posthog.api.oauth.cimd import _blocked_key, block_cimd_url, is_cimd_url_blocked
from posthog.models.oauth import CIMDBlocklistEntry

BLOCKED_URL = "https://partner.example.com/.well-known/oauth-client.json"


class TestCIMDBlocklistEntryAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.admin = CIMDBlocklistEntryAdmin(CIMDBlocklistEntry, AdminSite())

    def _request(self):
        request = RequestFactory().post("/")
        request.user = self.user
        return request

    @parameterized.expand([("delete_model",), ("delete_queryset",)])
    def test_removing_an_entry_also_clears_the_cached_block(self, removal_path):
        block_cimd_url(BLOCKED_URL)
        assert is_cimd_url_blocked(BLOCKED_URL) is True
        entry = CIMDBlocklistEntry.objects.get(cimd_url=BLOCKED_URL)
        queryset = CIMDBlocklistEntry.objects.filter(pk=entry.pk)
        request = self._request()

        if removal_path == "delete_model":
            self.admin.delete_model(request, entry)
        else:
            self.admin.delete_queryset(request, queryset)

        assert not CIMDBlocklistEntry.objects.filter(cimd_url=BLOCKED_URL).exists()
        assert is_cimd_url_blocked(BLOCKED_URL) is False

    def test_adding_an_entry_blocks_a_url_already_cached_as_allowed(self):
        assert is_cimd_url_blocked(BLOCKED_URL) is False
        request = self._request()
        form = self.admin.get_form(request)(data={"cimd_url": BLOCKED_URL, "reason": "abuse"})

        self.admin.save_model(request, CIMDBlocklistEntry(cimd_url=BLOCKED_URL, reason="abuse"), form, change=False)

        assert is_cimd_url_blocked(BLOCKED_URL) is True
        assert CIMDBlocklistEntry.objects.filter(cimd_url=BLOCKED_URL).count() == 1
        entry = CIMDBlocklistEntry.objects.get(cimd_url=BLOCKED_URL)
        assert entry.created_by == self.user

    @parameterized.expand(
        [
            ("uncached", None, "not cached (warms to blocked)"),
            ("blocked", True, "blocked"),
            ("stale_allowed", False, "STALE: cached as allowed"),
        ]
    )
    def test_cache_state_reports_the_cached_verdict_without_warming_it(self, _name, cached, expected):
        entry = CIMDBlocklistEntry.objects.create(cimd_url=BLOCKED_URL)
        if cached is not None:
            cache.set(_blocked_key(BLOCKED_URL), cached, timeout=60)

        assert self.admin.cache_state(entry) == expected
        assert cache.get(_blocked_key(BLOCKED_URL)) == cached
