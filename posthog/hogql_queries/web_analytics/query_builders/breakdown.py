from collections.abc import Callable

from pydantic.dataclasses import dataclass

from posthog.schema import WebStatsBreakdown

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

BREAKDOWN_NULL_DISPLAY = "(none)"

PathCleaner = Callable[[ast.Expr], ast.Expr]


@dataclass(frozen=True)
class BreakdownConfig:
    field_chain: tuple[str, ...] | None = None

    expr_builder: Callable[[PathCleaner], ast.Expr] | None = None

    apply_path_cleaning: bool = False

    # Set the default where experssion to filter out null breakdowns
    where_expr: str = "breakdown_value IS NOT NULL"

    def build_expr(self, path_cleaner: PathCleaner) -> ast.Expr:
        if self.expr_builder:
            expr = self.expr_builder(path_cleaner)
        elif self.field_chain:
            expr = ast.Field(chain=list(self.field_chain))
        else:
            raise ValueError("BreakdownConfig must have either field_chain or expr_builder")

        if self.apply_path_cleaning:
            expr = path_cleaner(expr)
        return expr

    def build_where_expr(self) -> ast.Expr:
        return parse_expr(self.where_expr)


def _build_previous_page_expr(path_cleaner: PathCleaner) -> ast.Expr:
    return ast.Call(
        name="multiIf",
        args=[
            # if it's internal navigation within a SPA, use the previous pageview's pathname
            ast.Call(
                name="isNotNull",
                args=[ast.Field(chain=["events", "properties", "$prev_pageview_pathname"])],
            ),
            path_cleaner(ast.Field(chain=["events", "properties", "$prev_pageview_pathname"])),
            # if it's internal navigation but not within a SPA, the referrer will be on the same domain, and path cleaning should still be applied
            ast.Call(
                name="equals",
                args=[
                    ast.Call(name="domain", args=[ast.Field(chain=["events", "properties", "$current_url"])]),
                    ast.Call(name="domain", args=[ast.Field(chain=["events", "properties", "$referrer"])]),
                ],
            ),
            path_cleaner(ast.Call(name="path", args=[ast.Field(chain=["events", "properties", "$referrer"])])),
            # a visit from an external domain
            ast.Field(chain=["events", "properties", "$referrer"]),
        ],
    )


def _build_utm_source_medium_campaign_expr() -> ast.Expr:
    return ast.Call(
        name="concatWithSeparator",
        args=[
            ast.Constant(value=" / "),
            _coalesce_with_null_display(
                ast.Field(chain=["session", "$entry_utm_source"]),
                ast.Field(chain=["session", "$entry_referring_domain"]),
            ),
            _coalesce_with_null_display(ast.Field(chain=["session", "$entry_utm_medium"])),
            _coalesce_with_null_display(ast.Field(chain=["session", "$entry_utm_campaign"])),
        ],
    )


def _build_viewport_expr() -> ast.Expr:
    return ast.Tuple(
        exprs=[
            ast.Field(chain=["properties", "$viewport_width"]),
            ast.Field(chain=["properties", "$viewport_height"]),
        ]
    )


def _build_region_expr() -> ast.Expr:
    return parse_expr(
        "tuple(properties.$geoip_country_code, properties.$geoip_subdivision_1_code, properties.$geoip_subdivision_1_name)"
    )


def _build_city_expr() -> ast.Expr:
    return parse_expr("tuple(properties.$geoip_country_code, properties.$geoip_city_name)")


def _build_timezone_expr() -> ast.Expr:
    # Value is in minutes, turn it to hours, works even for fractional timezone offsets (I'm looking at you, Australia)
    # see the docs here for why this the negative is necessary
    # https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date/getTimezoneOffset#negative_values_and_positive_values
    # the example given is that for UTC+10, -600 will be returned.
    return parse_expr("-toFloat(properties.$timezone_offset) / 60")


def _coalesce_with_null_display(*exprs: ast.Expr) -> ast.Expr:
    return ast.Call(name="coalesce", args=[*exprs, ast.Constant(value=BREAKDOWN_NULL_DISPLAY)])


BREAKDOWN_CONFIGS: dict[WebStatsBreakdown, BreakdownConfig] = {
    WebStatsBreakdown.PAGE: BreakdownConfig(
        field_chain=("events", "properties", "$pathname"),
        apply_path_cleaning=True,
    ),
    WebStatsBreakdown.INITIAL_PAGE: BreakdownConfig(
        field_chain=("session", "$entry_pathname"),
        apply_path_cleaning=True,
    ),
    WebStatsBreakdown.EXIT_PAGE: BreakdownConfig(
        field_chain=("session", "$end_pathname"),
        apply_path_cleaning=True,
    ),
    WebStatsBreakdown.FRUSTRATION_METRICS: BreakdownConfig(
        field_chain=("events", "properties", "$pathname"),
        apply_path_cleaning=True,
    ),
    WebStatsBreakdown.EXIT_CLICK: BreakdownConfig(
        field_chain=("session", "$last_external_click_url"),
    ),
    WebStatsBreakdown.INITIAL_REFERRING_DOMAIN: BreakdownConfig(
        field_chain=("session", "$entry_referring_domain"),
    ),
    WebStatsBreakdown.INITIAL_UTM_SOURCE: BreakdownConfig(
        field_chain=("session", "$entry_utm_source"),
        where_expr="TRUE",
    ),
    WebStatsBreakdown.INITIAL_UTM_CAMPAIGN: BreakdownConfig(
        field_chain=("session", "$entry_utm_campaign"),
        where_expr="TRUE",
    ),
    WebStatsBreakdown.INITIAL_UTM_MEDIUM: BreakdownConfig(
        field_chain=("session", "$entry_utm_medium"),
        where_expr="TRUE",
    ),
    WebStatsBreakdown.INITIAL_UTM_TERM: BreakdownConfig(
        field_chain=("session", "$entry_utm_term"),
        where_expr="TRUE",
    ),
    WebStatsBreakdown.INITIAL_UTM_CONTENT: BreakdownConfig(
        field_chain=("session", "$entry_utm_content"),
        where_expr="TRUE",
    ),
    WebStatsBreakdown.INITIAL_CHANNEL_TYPE: BreakdownConfig(
        field_chain=("session", "$channel_type"),
        # we need to check for empty strings as well due to how the left join works
        where_expr="breakdown_value IS NOT NULL AND breakdown_value != ''",
    ),
    WebStatsBreakdown.SCREEN_NAME: BreakdownConfig(
        field_chain=("events", "properties", "$screen_name"),
    ),
    WebStatsBreakdown.BROWSER: BreakdownConfig(
        field_chain=("properties", "$browser"),
    ),
    WebStatsBreakdown.OS: BreakdownConfig(
        field_chain=("properties", "$os"),
    ),
    WebStatsBreakdown.DEVICE_TYPE: BreakdownConfig(
        field_chain=("properties", "$device_type"),
    ),
    WebStatsBreakdown.COUNTRY: BreakdownConfig(
        field_chain=("properties", "$geoip_country_code"),
    ),
    WebStatsBreakdown.LANGUAGE: BreakdownConfig(
        field_chain=("properties", "$browser_language"),
    ),
    WebStatsBreakdown.PREVIOUS_PAGE: BreakdownConfig(
        expr_builder=_build_previous_page_expr,
    ),
    WebStatsBreakdown.INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN: BreakdownConfig(
        expr_builder=_build_utm_source_medium_campaign_expr,
    ),
    WebStatsBreakdown.VIEWPORT: BreakdownConfig(
        expr_builder=_build_viewport_expr,
        where_expr="tupleElement(breakdown_value, 1) IS NOT NULL AND tupleElement(breakdown_value, 2) IS NOT NULL AND tupleElement(breakdown_value, 1) != 0 AND tupleElement(breakdown_value, 2) != 0",
    ),
    WebStatsBreakdown.REGION: BreakdownConfig(
        expr_builder=_build_region_expr,
        where_expr="tupleElement(breakdown_value, 2) IS NOT NULL",
    ),
    WebStatsBreakdown.CITY: BreakdownConfig(
        expr_builder=_build_city_expr,
        where_expr="tupleElement(breakdown_value, 2) IS NOT NULL",
    ),
    WebStatsBreakdown.TIMEZONE: BreakdownConfig(
        expr_builder=_build_timezone_expr,
    ),
}
