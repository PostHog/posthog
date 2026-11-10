import './Today.scss'

import { IconRocket } from '@posthog/icons'

import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { TodayHomeHeading } from './TodayHomeHeading'
import { TodayRow } from './TodayRow'

export function TodayNewProjectForYou(): JSX.Element {
    return (
        <section className="TodayHome__list" aria-label="For you today">
            <div className="TodayHome__headingRow">
                <TodayHomeHeading>For you today</TodayHomeHeading>
            </div>
            <ol className="TodayRows">
                <TodayRow
                    tone="neutral"
                    icon={{ color: 'var(--color-product-product-analytics-light)', glyph: <IconRocket /> }}
                    title="Install PostHog"
                    facts={['Send your first events. Then what needs you shows up here.']}
                    to={urls.onboarding({
                        productKey: ProductKey.PRODUCT_ANALYTICS,
                        stepKey: OnboardingStepKey.INSTALL,
                    })}
                    dataAttr="today-install-row"
                />
            </ol>
        </section>
    )
}
