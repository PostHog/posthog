import * as townCrierPng from '@posthog/brand/hoggies/png/town-crier'
import { LemonBanner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

const HedgehogTownCrier = pngHoggie(townCrierPng)

export function TaggersDeprecationBanner(): JSX.Element {
    return (
        <LemonBanner
            type="warning"
            // The banner is a size container, so the hog only takes text width when there is room for it.
            icon={<HedgehogTownCrier className="hidden @lg:block w-16 h-16 shrink-0" />}
            action={{
                children: 'Create a categorical evaluation',
                to: urls.aiObservabilityEvaluationTemplates(),
                'data-attr': 'taggers-deprecation-banner-create-evaluation',
            }}
        >
            <p className="font-semibold">Taggers are being retired</p>
            <p>
                New taggers can't be created. To tag generations, create an evaluation with a categorical output. Your
                existing taggers keep running for now, and we'll let you know before they stop.
            </p>
        </LemonBanner>
    )
}
