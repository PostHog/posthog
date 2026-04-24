import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from parameterized import parameterized

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

        with pytest.raises(ValueError, match="Unsupported error tracking filter key"):
            property_to_django_filter(
                qs,
                ErrorTrackingIssueFilter(
                    key="assignment__user__password", value="x", operator=PropertyOperator.ICONTAINS
                ),
            )

        with pytest.raises(ValueError, match="Unsupported error tracking filter key"):
            property_to_django_filter(
                qs,
                ErrorTrackingIssueFilter(key="team__api_token", value="x", operator=PropertyOperator.ICONTAINS),
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

    @parameterized.expand(
        [
            (PropertyOperator.EXACT,),
            (PropertyOperator.IS_NOT,),
            (PropertyOperator.NOT_IN,),
            (PropertyOperator.ICONTAINS,),
            (PropertyOperator.NOT_ICONTAINS,),
            (PropertyOperator.REGEX,),
            (PropertyOperator.NOT_REGEX,),
            (PropertyOperator.GT,),
            (PropertyOperator.GTE,),
            (PropertyOperator.LT,),
            (PropertyOperator.LTE,),
            (PropertyOperator.IS_DATE_EXACT,),
            (PropertyOperator.IS_DATE_AFTER,),
            (PropertyOperator.IS_DATE_BEFORE,),
        ]
    )
    def test_none_value_is_no_op_for_non_set_operators(self, operator):
        # Regression: half-filled issue property filters arriving with value=None previously bubbled
        # up as "Cannot use None as a query value" from Django. Now they should be a silent no-op,
        # mirroring the existing behavior for array operators with empty values.
        qs = MagicMock()
        qs.filter = MagicMock()
        qs.exclude = MagicMock()

        result = property_to_django_filter(qs, ErrorTrackingIssueFilter(key="name", value=None, operator=operator))

        assert result is qs
        qs.filter.assert_not_called()
        qs.exclude.assert_not_called()

    @parameterized.expand([(PropertyOperator.IS_SET,), (PropertyOperator.IS_NOT_SET,)])
    def test_is_set_operators_ignore_value(self, operator):
        # IS_SET / IS_NOT_SET synthesize value=True via __isnull, so None input must still apply the filter.
        qs = MagicMock()
        qs.filter = MagicMock()
        qs.exclude = MagicMock()

        property_to_django_filter(qs, ErrorTrackingIssueFilter(key="name", value=None, operator=operator))

        if operator == PropertyOperator.IS_SET:
            qs.exclude.assert_called_once_with(name__isnull=True)
        else:
            qs.filter.assert_called_once_with(name__isnull=True)
