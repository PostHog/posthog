from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from posthog.models import Event, User, Team, Person, Element, Funnel, FunnelStep, Action, ActionStep

admin.site.register(User, UserAdmin)
admin.site.register(Team)
admin.site.register(Person)
admin.site.register(Element)
admin.site.register(Funnel)
admin.site.register(FunnelStep)
admin.site.register(Action)
admin.site.register(ActionStep)

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    readonly_fields = ('timestamp',)
    list_display = ('timestamp', 'event', 'id',)

    def get_queryset(self, request):
        qs = super(EventAdmin, self).get_queryset(request)
        return qs.order_by('-timestamp')
 