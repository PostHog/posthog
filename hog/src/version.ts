import pkg from '../package.json' with { type: 'json' }

// The release workflow sets both with `bun build --define`. A local build or a run from source has
// neither, so it reports the version in package.json and counts as a dev build.
declare const HOG_RELEASE_VERSION: string | undefined
declare const HOG_BUILD_DATE: string | undefined

export const VERSION: string = typeof HOG_RELEASE_VERSION === 'string' ? HOG_RELEASE_VERSION : pkg.version

export const BUILD_DATE: string | undefined = typeof HOG_BUILD_DATE === 'string' ? HOG_BUILD_DATE : undefined
