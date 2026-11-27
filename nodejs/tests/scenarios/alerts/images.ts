import { execFileSync } from 'child_process'

export const VICTORIA_METRICS_IMAGE =
    'victoriametrics/victoria-metrics:v1.136.0@sha256:593b533bfbea439f2fd8aed306294cb6a5b362e7932681ebb476cc6aaef70841'
export const VMALERT_IMAGE =
    'victoriametrics/vmalert:v1.136.0@sha256:e756ea8839f295b4e789a739c3ac80d70404e11b918973506a6182aacca2b11e'

if (require.main === module) {
    for (const image of [VICTORIA_METRICS_IMAGE, VMALERT_IMAGE]) {
        execFileSync('docker', ['pull', image], { stdio: 'inherit', timeout: 300_000 })
    }
}
