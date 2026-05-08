from django.contrib import admin


class DeletedFilter(admin.SimpleListFilter):
    """Sidebar filter for models with a soft-delete `deleted` boolean, defaulting to hiding deleted rows."""

    title = "deleted"
    parameter_name = "deleted"

    def lookups(self, request, model_admin):
        return (("no", "No"), ("yes", "Yes"), ("all", "All"))

    def choices(self, changelist):
        value = self.value() or "no"
        for lookup, title in self.lookup_choices:
            yield {
                "selected": value == lookup,
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }

    def queryset(self, request, queryset):
        value = self.value() or "no"
        if value == "no":
            return queryset.filter(deleted=False)
        if value == "yes":
            return queryset.filter(deleted=True)
        return queryset
