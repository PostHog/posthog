from rest_framework import serializers

from products.business_knowledge.backend.github_repos import MAX_GITHUB_REPOS, RepositoryCacheStatus, RepositoryHitKind


class RepositoryConnectionSerializer(serializers.Serializer):
    connected = serializers.BooleanField(help_text="True when a GitHub installation is connected for this environment.")
    integration_id = serializers.IntegerField(
        allow_null=True,
        help_text="Connected GitHub integration id, or null when GitHub is not connected.",
    )
    integration_name = serializers.CharField(
        help_text="GitHub account name for the connected installation. Empty when GitHub is not connected."
    )
    repos = serializers.ListField(
        child=serializers.CharField(),
        help_text="Lowercased owner/repo names business knowledge is allowed to read.",
    )


class RepositoryConnectSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="Id of a GitHub integration on this environment.")


class RepositorySelectionSerializer(serializers.Serializer):
    repos = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
        max_length=MAX_GITHUB_REPOS,
        help_text=f"owner/repo names to allow. At most {MAX_GITHUB_REPOS}. Replaces the current list.",
    )


class RepositorySearchQuerySerializer(serializers.Serializer):
    query = serializers.CharField(help_text="File names, path fragments, or identifiers to match. Not a full sentence.")
    repo = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Limit the search to this owner/repo. It must already be selected. Omit to search every selected repository.",
    )


class RepositoryFileQuerySerializer(serializers.Serializer):
    repo = serializers.CharField(help_text="owner/repo to read. It must already be selected.")
    path = serializers.CharField(help_text="File path returned by the repository search.")


class RepositorySearchHitSerializer(serializers.Serializer):
    repo = serializers.CharField(help_text="Lowercased owner/repo the hit came from.")
    path = serializers.CharField(help_text="File path. Empty for a README hit.")
    url = serializers.URLField(help_text="Permalink for the hit. Cite this when you use the hit.")
    kind = serializers.ChoiceField(
        choices=RepositoryHitKind.choices,
        help_text="path is a file name match. readme is a short excerpt of the repository README.",
    )
    excerpt = serializers.CharField(help_text="Short README excerpt. Empty for a path hit.")


class RepositoryCacheStateSerializer(serializers.Serializer):
    repo = serializers.CharField(help_text="Lowercased owner/repo.")
    tree_truncated = serializers.BooleanField(
        help_text="True when the cached file list is incomplete because the repository has too many files."
    )
    cache_status = serializers.ChoiceField(
        choices=RepositoryCacheStatus.choices,
        help_text="ready means the file list was cached recently. warming means a refresh was just queued.",
    )


class RepositorySearchResponseSerializer(serializers.Serializer):
    results = RepositorySearchHitSerializer(many=True, help_text="Path matches, then README excerpts.")
    repositories = RepositoryCacheStateSerializer(
        many=True, help_text="Cache state for each repository that was searched."
    )


class RepositoryFileSerializer(serializers.Serializer):
    repo = serializers.CharField(help_text="Lowercased owner/repo.")
    path = serializers.CharField(help_text="File path that was read.")
    url = serializers.URLField(
        help_text="Permalink for this file at the cached commit. Cite this when you use the file."
    )
    content = serializers.CharField(help_text="File text, cut off at 32,000 characters.")
    truncated = serializers.BooleanField(help_text="True when content was cut off at 32,000 characters.")
