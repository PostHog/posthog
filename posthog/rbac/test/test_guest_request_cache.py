from posthog.test.base import BaseTest

from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest

from posthog.models import Organization, OrganizationMembership
from posthog.rbac.guest_request_cache import (
    get_user_guest_membership,
    get_user_guest_org_ids,
    is_user_guest_in_any_org,
    is_user_guest_in_org,
)


def _make_request(user) -> HttpRequest:
    request = HttpRequest()
    request.user = user
    return request


class TestGuestRequestCache(BaseTest):
    def setUp(self):
        super().setUp()
        # `BaseTest` provides `self.user` and `self.organization`. Add a second org
        # where the user is a guest so we can exercise the union behavior.
        self.guest_org = Organization.objects.create(name="Guest org")
        OrganizationMembership.objects.create(
            user=self.user, organization=self.guest_org, is_guest=True, level=OrganizationMembership.Level.MEMBER
        )

    def test_anonymous_user_has_no_guest_orgs(self):
        request = _make_request(AnonymousUser())
        self.assertEqual(get_user_guest_org_ids(request), frozenset())

    def test_request_without_user_has_no_guest_orgs(self):
        request = HttpRequest()
        self.assertEqual(get_user_guest_org_ids(request), frozenset())

    def test_returns_only_orgs_where_user_is_guest(self):
        request = _make_request(self.user)
        self.assertEqual(get_user_guest_org_ids(request), frozenset({self.guest_org.id}))

    def test_caches_result_on_request(self):
        request = _make_request(self.user)
        # First call hits the DB; second call must use cached value even if the
        # underlying queryset would now return something different.
        first = get_user_guest_org_ids(request)
        # Mutate underlying state — cache should not reflect the change.
        OrganizationMembership.objects.filter(user=self.user, organization=self.guest_org).update(is_guest=False)
        second = get_user_guest_org_ids(request)
        self.assertEqual(first, second)
        self.assertIn(self.guest_org.id, second)

    def test_is_user_guest_in_any_org(self):
        self.assertTrue(is_user_guest_in_any_org(_make_request(self.user)))

        non_guest_user = self._create_user("non-guest@test.com")
        self.assertFalse(is_user_guest_in_any_org(_make_request(non_guest_user)))

    def test_is_user_guest_in_org_with_uuid_or_string(self):
        request = _make_request(self.user)
        self.assertTrue(is_user_guest_in_org(request, self.guest_org.id))
        self.assertTrue(is_user_guest_in_org(request, str(self.guest_org.id)))
        self.assertFalse(is_user_guest_in_org(request, self.organization.id))

    def test_get_user_guest_membership_returns_cached_membership(self):
        request = _make_request(self.user)
        m1 = get_user_guest_membership(request, self.guest_org.id)
        m2 = get_user_guest_membership(request, self.guest_org.id)
        assert m1 is not None
        self.assertIs(m1, m2)  # same instance from request cache
        self.assertTrue(m1.is_guest)

    def test_get_user_guest_membership_returns_none_for_non_guest_org(self):
        request = _make_request(self.user)
        self.assertIsNone(get_user_guest_membership(request, self.organization.id))

    def test_consolidates_repeated_lookups_into_single_query(self):
        request = _make_request(self.user)
        with self.assertNumQueries(1):
            for _ in range(5):
                is_user_guest_in_any_org(request)
                is_user_guest_in_org(request, self.guest_org.id)
                is_user_guest_in_org(request, self.organization.id)
