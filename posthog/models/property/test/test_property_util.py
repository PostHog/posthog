import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock

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

    def test_unimplemented_filter_types_raise(self):
        qs = MagicMock()

        with pytest.raises(NotImplementedError):
            property_to_django_filter(
                qs,
                ErrorTrackingIssueFilter(
                    key="issue_description", value=["description"], operator=PropertyOperator.BETWEEN
                ),
            )
