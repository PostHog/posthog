// Story files resolve their own copy of `storybook`, so the parameter types live here, where they augment that copy.
import type { Mocks } from '~/mocks/utils'

export type ViewportWidthName = 'narrow' | 'medium' | 'wide' | 'superwide'
// 'firefox' is technically supported too, but as of June 2023 it has memory usage issues that make is unusable
export type SupportedBrowserName = 'chromium' | 'webkit'
export type SnapshotTheme = 'light' | 'dark'

declare module 'storybook/internal/types' {
    interface Parameters {
        options?: any
        /** @default 'padded' */
        layout?: 'padded' | 'fullscreen' | 'centered'
        testOptions?: {
            /**
             * Whether we should wait for all loading indicators to disappear before taking a snapshot.
             * @default true
             */
            waitForLoadersToDisappear?: boolean
            /** If set, we'll wait for the given selector (or all selectors, if multiple) to be satisfied. */
            waitForSelector?: string | string[]
            /** Timeout in ms for waitForSelector. Defaults to Playwright's context timeout (PLAYWRIGHT_TIMEOUT_MS). */
            waitForSelectorTimeout?: number
            /**
             * Override the per-test Jest timeout (ms) for stories whose render legitimately needs
             * longer than the default. Use sparingly — a slow story is usually a bug, not a budget
             * problem. Still scaled by the viewport-widths multiplier. Defaults to JEST_TIMEOUT_MS.
             */
            jestTimeout?: number
            /**
             * By default we wait for images to have width as an indication the page is ready for screenshot testing
             * Some stories have broken images on purpose to test what the UI does
             * in those cases set `allowImagesWithoutWidth` to `true`
             */
            allowImagesWithoutWidth?: boolean
            /**
             * Whether navigation should be included in the snapshot. Only applies to `layout: 'fullscreen'` stories.
             * @default false
             */
            includeNavigationInSnapshot?: boolean
            /**
             * The test will always run for all the browers, but snapshots are only taken in Chromium by default.
             * Override this to take snapshots in other browsers too.
             *
             * @default ['chromium']
             */
            snapshotBrowsers?: SupportedBrowserName[]
            /** Narrow the snapshot to a specific element. Only works for component (non-fullscreen) snapshots — throws an error if used with `layout: 'fullscreen'`. */
            snapshotTargetSelector?: string
            /** specify an alternative viewport size */
            viewport?: { width: number; height: number }
            /** take snapshots at multiple preset widths, producing one snapshot per width */
            viewportWidths?: ViewportWidthName[]
            /**
             * Skip waiting for iframes to load. Useful for stories with external iframes that fail in CI.
             * Also skips waiting for networkidle, which is useful for stories with background network activity.
             * @default false
             */
            skipIframeWait?: boolean
            /**
             * Skip taking a dark mode snapshot. Useful for stories that don't support dark mode or have known issues in dark mode that would cause snapshot failures.
             */
            skipDarkMode?: boolean
            /**
             * Skip taking a light mode snapshot. Useful for stories that pin themselves to dark mode
             * (e.g. via story globals plus a mocked `theme_mode: 'dark'` user), where the light
             * snapshot would render dark-computed values on a light background.
             */
            skipLightMode?: boolean
            /**
             * Suppress quill-charts canvas painting for this story's snapshot, avoiding flake from
             * the charts' async paint. Handled by the `withChartCanvasSnapshot` decorator.
             * @default false
             */
            skipCanvasDraw?: boolean
        }
        /** Flags that are on (`string[]`), or flags pinned to a value or variant (`Record`). Applied by `withFeatureFlags`. */
        featureFlags?: string[] | Record<string, string | boolean>
        /** Pins the clock with MockDate. Applied by `withMockDate`. */
        mockDate?: string | number | Date
        /** Pushed to the kea router after the story mounts. Applied by `withPageUrl`. */
        pageUrl?: string
        msw?: {
            mocks?: Mocks
        }
        [name: string]: any
    }

    interface Globals {
        theme: SnapshotTheme
    }
}
