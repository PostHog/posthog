import { mkdir } from 'fs/promises'
import { dirname, join } from 'path'

import { test } from '../utils/playwright-test-base'

import { features } from './features'
import { uploadShot } from './upload'

const OUTPUT_DIR = process.env.DOCS_CAPTURE_OUTPUT_DIR || join(__dirname, 'output')

/** Pinned to keep shots consistent between local + CI and to match posthog.com docs rendering. */
const VIEWPORT = { width: 1440, height: 900 } as const

test.describe('docs capture', () => {
    test.use({ viewport: VIEWPORT })

    for (const feature of features) {
        test(feature.slug, async ({ page }) => {
            await feature.setup(page)

            const featureLocator = page.locator(`[data-feature="${feature.slug}"]`).first()

            for (const [name, mutate] of Object.entries(feature.shots)) {
                await mutate(page)
                const path = join(OUTPUT_DIR, feature.slug, `${name}.png`)
                await mkdir(dirname(path), { recursive: true })
                // Scope the shot to the tagged element — that's the contract: the slug picks the
                // region of the screen, not the whole page. Falls back to viewport if the element
                // lives in a popover that's not measurable.
                if (await featureLocator.boundingBox().catch(() => null)) {
                    await featureLocator.screenshot({ path })
                } else {
                    await page.screenshot({ path, fullPage: false })
                }
                await uploadShot({ slug: feature.slug, name, path, docsPath: feature.docsPath })
            }
        })
    }
})
