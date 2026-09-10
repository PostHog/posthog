# Test cases for taxonomy-scope-uses-project-key.
# ruff: noqa


# ruleid: taxonomy-scope-uses-project-key
PropertyDefinition.objects.filter(team=team, name__in=names)

# ruleid: taxonomy-scope-uses-project-key
PropertyDefinition.objects.get(team=self._team, name=property_name, type=PropertyDefinition.Type.EVENT)

# ruleid: taxonomy-scope-uses-project-key
EventDefinition.objects.filter(team_id=view.team_id, name=value).exists()

# ruleid: taxonomy-scope-uses-project-key
EventProperty.objects.filter(team_id=team.pk, event__in=events).order_by("event", "property")

# ruleid: taxonomy-scope-uses-project-key
EnterprisePropertyDefinition.objects.filter(team=team, type=property_type, name__in=names).exclude(description="")

# ruleid: taxonomy-scope-uses-project-key
PropertyDefinition.objects.filter(type=PropertyDefinition.Type.PERSON).filter(team_id=team_id)

# ruleid: taxonomy-scope-uses-project-key
EventDefinition.objects.exclude(team=team)

# ok: taxonomy-scope-uses-project-key
PropertyDefinition.objects.for_project(team.project_id).filter(name__in=names)

# ok: taxonomy-scope-uses-project-key
EventDefinition.objects.for_project(view.project_id).filter(name=value).exists()

# ok: taxonomy-scope-uses-project-key
PropertyDefinition.objects.get(id=property_definition_id, team_id=self.team_id)

# ok: taxonomy-scope-uses-project-key
EventDefinition.objects.filter(id__in=ids, team_id=team_id)

# ok: taxonomy-scope-uses-project-key
PropertyDefinition.objects.create(team=team, name="plan", type=PropertyDefinition.Type.PERSON)

# ok: taxonomy-scope-uses-project-key
EventDefinition.objects.get_or_create(team=team, name=name, defaults={"project_id": team.project_id})

# ok: taxonomy-scope-uses-project-key
Action.objects.filter(team=team, deleted=False)

# ok: taxonomy-scope-uses-project-key
MaterializedColumnSlot.objects.filter(team_id=team_id)

# nosemgrep: taxonomy-scope-uses-project-key -- cleanup deletes by team on purpose
PropertyDefinition.objects.filter(team_id=team_id, type=definition_type, name__in=batch).delete()
