import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from rest_framework import exceptions

from posthog.schema import ErrorTrackingIssueFilter, PropertyOperator

from posthog.models.property.util import property_to_django_filter


class TestPropertyUtil(BaseTest):
    def test_property_to_django_filtering(self):
        qs = MagicMock()
        qs.filter = MagicMock()
        qs.exclude = MagicMock()

        # does not filter falsey exact matches
        property_to_django_filter(qs, ErrorTrackingIssueFilter(key="name", value=None, operator=PropertyOperator.EXACT))
        qs.filter.assert_not_called()
        property_to_django_filter(qs, ErrorTrackingIssueFilter(key="name", value=[], operator=PropertyOperator.EXACT))
        qs.filter.assert_not_called()

        # array based options
        property_to_django_filter(
            qs, ErrorTrackingIssueFilter(key="name", value=["value"], operator=PropertyOperator.EXACT)
        )
        qs.filter.assert_called_once_with(name__in=["value"])
        qs.filter.reset_mock()

        # default options
        property_to_django_filter(
            qs, ErrorTrackingIssueFilter(key="name", value="value", operator=PropertyOperator.ICONTAINS)
        )
        qs.filter.assert_called_once_with(name__icontains="value")
        qs.filter.reset_mock()

        # negated filtering
        property_to_django_filter(
            qs, ErrorTrackingIssueFilter(key="name", value=["value"], operator=PropertyOperator.IS_NOT)
        )
        qs.exclude.assert_called_once_with(name__in=["value"])

    def test_issue_description_mapping(self):
        qs = MagicMock()
        qs.filter = MagicMock()

        property_to_django_filter(
            qs,
            ErrorTrackingIssueFilter(key="issue_description", value=["description"], operator=PropertyOperator.EXACT),
        )
        qs.filter.assert_called_once_with(description__in=["description"])
        qs.filter.reset_mock()

    def test_rejects_orm_traversal_keys(self):
        qs = MagicMock()

        with pytest.raises(exceptions.ValidationError, match="Unsupported error tracking filter key"):
            property_to_django_filter(
                qs,
                ErrorTrackingIssueFilter(
                    key="assignment__user__password", value="x", operator=PropertyOperator.ICONTAINS
                ),
            )

        with pytest.raises(exceptions.ValidationError, match="Unsupported error tracking filter key"):
            property_to_django_filter(
                qs,
                ErrorTrackingIssueFilter(key="team__api_token", value="x", operator=PropertyOperator.ICONTAINS),
            )

        qs.filter.assert_not_called()

    def test_rejects_unknown_issue_filter_keys_with_validation_error(self):
        # Regression: unknown issue-typed keys (e.g. "$environment") previously raised an
        # unhandled ValueError which surfaced as a 500 in the v1 query runner. They should
        # now raise a DRF ValidationError so the API returns a 400.
        qs = MagicMock()

        with pytest.raises(exceptions.ValidationError, match="Unsupported error tracking filter key"):
            property_to_django_filter(
                qs,
                ErrorTrackingIssueFilter(key="$environment", value="prod", operator=PropertyOperator.EXACT),
            )

        qs.filter.assert_not_called()

    def test_unimplemented_filter_types_raise(self):
        qs = MagicMock()

        with pytest.raises(NotImplementedError):
            property_to_django_filter(
                qs,
                ErrorTrackingIssueFilter(
                    key="issue_description", value=["description"], operator=PropertyOperator.BETWEEN
                ),
            )
