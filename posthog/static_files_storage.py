from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class NonStrictManifestStaticFilesStorage(ManifestStaticFilesStorage):
    # esbuild emits hashed CSS/JS chunks with `sourceMappingURL` comments that
    # Django's strict manifest post-processing tries to resolve against
    # STATIC_ROOT. Code-split CSS chunks for lazy-loaded scenes occasionally
    # ship without a matching `.css.map` (esbuild's CSS code-splitting is still
    # evolving), which would otherwise turn a missing source map into a hard
    # `collectstatic` failure and break the Docker image build.
    manifest_strict = False
