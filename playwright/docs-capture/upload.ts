/**
 * Stub for the upload + docs-PR step. Wire this up after the capture loop is stable.
 *
 * Intended flow:
 *   1. Upload `path` to S3 at `s3://posthog-website-assets/auto/<slug>/<name>.png`.
 *   2. On the final shot for a slug, open/refresh a PR against posthog/website that:
 *      - swaps the image URL inside `docsPath`'s .mdx,
 *      - leaves a visual diff comment for a human reviewer.
 *
 * Until that's wired, we only log — running the spec produces local screenshots in `output/`.
 */
export interface UploadInput {
    slug: string
    name: string
    path: string
    docsPath: string
}

export async function uploadShot(input: UploadInput): Promise<void> {
    if (!process.env.DOCS_CAPTURE_UPLOAD) {
        return
    }
    // TODO: implement S3 upload + posthog/website PR.
    // Deliberately not stubbing the SDK call — the real implementation should pull credentials
    // from CI secrets and live behind a single `aws s3 cp` or `@aws-sdk/client-s3` call.
    // eslint-disable-next-line no-console
    console.log(`[docs-capture] would upload ${input.path} for ${input.slug}/${input.name}`)
}
