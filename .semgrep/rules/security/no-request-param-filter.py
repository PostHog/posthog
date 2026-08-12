from django.contrib.auth.models import User

# === SHOULD BE CAUGHT (ruleid) ===


def direct_dict(request):
    # ruleid: no-request-param-orm-filter
    return User.objects.filter(**request.GET.dict())


def direct_querydict(request):
    # ruleid: no-request-param-orm-filter
    return User.objects.filter(**request.GET)


def direct_post(request):
    # ruleid: no-request-param-orm-filter
    return User.objects.filter(**request.POST)


def direct_query_params(request):
    # ruleid: no-request-param-orm-filter
    return User.objects.filter(**request.query_params)


def direct_data(request):
    # ruleid: no-request-param-orm-filter
    return User.objects.filter(**request.data)


def indirect_filter(request):
    params = request.GET.dict()
    # ruleid: no-request-param-orm-filter
    return User.objects.filter(**params)


def indirect_querydict(request):
    params = request.POST
    # ruleid: no-request-param-orm-filter
    return User.objects.filter(**params)


def exclude_injection(request):
    # ruleid: no-request-param-orm-filter
    return User.objects.exclude(**request.GET.dict())


def get_injection(request):
    # ruleid: no-request-param-orm-filter
    return User.objects.get(**request.GET.dict())


def create_injection(request):
    data = request.POST.dict()
    # ruleid: no-request-param-orm-filter
    return User.objects.create(**data)


def update_injection(request):
    data = request.data
    # ruleid: no-request-param-orm-filter
    User.objects.filter(id=1).update(**data)


def get_or_create_injection(request):
    params = request.query_params.dict()
    # ruleid: no-request-param-orm-filter
    return User.objects.get_or_create(**params)


def update_or_create_injection(request):
    # ruleid: no-request-param-orm-filter
    return User.objects.update_or_create(**request.POST)


def update_or_create_dict_injection(request):
    # ruleid: no-request-param-orm-filter
    return User.objects.update_or_create(**request.POST.dict())


# === SHOULD NOT BE CAUGHT (ok) ===


def safe_explicit_field(request):
    name = request.GET.get("name")
    # ok: no-request-param-orm-filter
    return User.objects.filter(name=name)


def safe_whitelisted_params(request):
    allowed = {"name", "email"}
    filters = {k: v for k, v in request.GET.dict().items() if k in allowed}
    # ok: no-request-param-orm-filter
    return User.objects.filter(**filters)


def safe_hardcoded_dict(request):
    filters = {"is_active": True}
    # ok: no-request-param-orm-filter
    return User.objects.filter(**filters)


def safe_from_different_source(get_external_config):
    # Data from non-request sources is safe
    external_data = get_external_config()
    # ok: no-request-param-orm-filter
    return User.objects.create(**external_data)
