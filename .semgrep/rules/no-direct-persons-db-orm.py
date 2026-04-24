# Test cases for no-direct-persons-db-orm

from posthog.models import Person, PersonDistinctId, Group, GroupTypeMapping, CohortPeople


def bad_person_filter(team_id: int):
    # ruleid: no-direct-persons-db-orm
    return Person.objects.filter(team_id=team_id)


def bad_person_get(team_id: int, uuid: str):
    # ruleid: no-direct-persons-db-orm
    return Person.objects.get(team_id=team_id, uuid=uuid)


def bad_person_db_manager(team_id: int):
    # ruleid: no-direct-persons-db-orm
    return Person.objects.db_manager("persons_db_reader").filter(team_id=team_id)


def bad_person_all():
    # ruleid: no-direct-persons-db-orm
    return Person.objects.all()


def bad_person_create(team_id: int):
    # ruleid: no-direct-persons-db-orm
    return Person.objects.create(team_id=team_id)


def bad_distinct_id_filter(team_id: int, distinct_id: str):
    # ruleid: no-direct-persons-db-orm
    return PersonDistinctId.objects.filter(team_id=team_id, distinct_id=distinct_id)


def bad_group_filter(team_id: int):
    # ruleid: no-direct-persons-db-orm
    return Group.objects.filter(team_id=team_id)


def bad_group_type_mapping_filter(project_id: int):
    # ruleid: no-direct-persons-db-orm
    return GroupTypeMapping.objects.filter(project_id=project_id)


def bad_cohort_people_filter(cohort_id: int):
    # ruleid: no-direct-persons-db-orm
    return CohortPeople.objects.filter(cohort_id=cohort_id)


def bad_person_chained(team_id: int):
    # ruleid: no-direct-persons-db-orm
    return Person.objects.filter(team_id=team_id).order_by("id")


def bad_person_bulk_create(persons: list):
    # ruleid: no-direct-persons-db-orm
    return Person.objects.bulk_create(persons)


# === Safe patterns ===


def ok_use_helper(team_id: int, uuid: str):
    from posthog.models.person.util import get_person_by_uuid

    # ok: no-direct-persons-db-orm
    return get_person_by_uuid(team_id, uuid)


def ok_use_group_helper(project_id: int):
    from posthog.models.group_type_mapping import get_group_types_for_project

    # ok: no-direct-persons-db-orm
    return get_group_types_for_project(project_id)


def ok_other_model_filter(team_id: int):
    from posthog.models import Dashboard

    # ok: no-direct-persons-db-orm
    return Dashboard.objects.filter(team_id=team_id)


def ok_user_model():
    from django.contrib.auth.models import User

    # ok: no-direct-persons-db-orm
    return User.objects.all()
