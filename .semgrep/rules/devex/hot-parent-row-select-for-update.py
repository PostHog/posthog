# Test cases for hot-parent-row-select-for-update.
# ruff: noqa


# ruleid: hot-parent-row-select-for-update
Team.objects.select_for_update().get(id=team_id)

# ruleid: hot-parent-row-select-for-update
Organization.objects.select_for_update(skip_locked=True).filter(id__in=organization_ids)

# ruleid: hot-parent-row-select-for-update
Team.objects.only("id").select_for_update().get(id=team_id)

# ruleid: hot-parent-row-select-for-update
Organization.objects.filter(is_active=True).order_by("id").select_for_update()

# ruleid: hot-parent-row-select-for-update
Team.objects.using("default").filter(is_active=True).only("id").order_by("id").select_for_update()

# ok: hot-parent-row-select-for-update
Team.objects.only("id").select_for_update(no_key=True).get(id=team_id)

# ok: hot-parent-row-select-for-update
Project.objects.select_for_update().get(id=project_id)

# ok: hot-parent-row-select-for-update
TeamConversationsSlackConfig.objects.select_for_update().get(team_id=team_id)

# ok: hot-parent-row-select-for-update
Team.objects.filter(id=team_id).first()

# ok: hot-parent-row-select-for-update
Organization.objects.only("id").filter(id=organization_id).exists()

# nosemgrep: hot-parent-row-select-for-update -- deleting the parent must block concurrent child inserts
Team.objects.select_for_update().filter(id__in=team_ids)
