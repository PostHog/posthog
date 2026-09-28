import { useActions } from 'kea'

import * as star from '@posthog/brand/hoggies/png/star'
import { Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'

import { navProductsTabLogic } from './navProductsTabLogic'

const HedgehogStar = pngHoggie(star)

export function StarredSetupIntro(): JSX.Element {
    const { confirmCleanSlate } = useActions(navProductsTabLogic)

    return (
        <section className="@container flex items-center gap-4 border-b pb-4">
            <div className="flex flex-1 flex-col gap-3">
                <p className="mb-0">
                    Many of you told us things were too hard to find in the old sidebar, so we simplified it. Your
                    sidebar now shows only the products you star.
                </p>
                <p className="mb-0">
                    Rather see everything?{' '}
                    <Link onClick={confirmCleanSlate} data-attr="starred-setup-clean-slate">
                        Start with a clean slate
                    </Link>{' '}
                    and star products as you go.
                </p>
                <p className="mb-0 text-secondary">
                    Looking for something specific? Press <KeyboardShortcut command k /> to open the{' '}
                    <strong>improved search</strong> and jump anywhere in PostHog.
                </p>
            </div>
            <HedgehogStar className="hidden h-32 w-auto shrink-0 @md:block" loading="eager" />
        </section>
    )
}
