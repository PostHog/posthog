import logging

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from posthog.admin.admins.addon_feature_usage_queries import TIER_LABELS, build_report

logger = logging.getLogger(__name__)


def addon_feature_usage_view(request):
    if not request.user.is_staff:
        raise PermissionDenied

    report = build_report()

    # Flatten each section into rows the template can iterate (Django templates
    # can't index a dict by the section's tier variable).
    sections = []
    for section in report.sections:
        rows = [{"feature": f, "tm": f.by_tier.get(section.tier)} for f in section.features]
        sections.append({"tier": section.tier, "label": section.label, "size": section.size, "rows": rows})

    summary_rows = [
        {"label": TIER_LABELS[t], "count": report.summary.get(t)}
        for t in ["free", "paid", "boost", "scale", "enterprise"]
    ]

    context = {
        **admin.site.each_context(request),
        "title": "Add-on feature adoption",
        "sections": sections,
        "summary_rows": summary_rows,
        "summary_error": report.summary.error,
        "excluded": report.excluded,
        "failures": report.failures,
    }
    return render(request, "admin/addon_feature_usage.html", context)
