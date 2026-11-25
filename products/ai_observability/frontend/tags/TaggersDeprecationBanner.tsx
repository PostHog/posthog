import * as townCrierPng from '@posthog/brand/hoggies/png/town-crier'
import { LemonBanner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

const HedgehogTownCrier = pngHoggie(townCrierPng)

export interface TaggersDeprecationBannerProps {
    /** On a tagger's page: the evaluation that replaced it. */
    migratedToEvaluationId?: string | null
    /** On the taggers list: whether any tagger was replaced by an evaluation. */
    someMigrated?: boolean
}

function bannerContent({ migratedToEvaluationId, someMigrated }: TaggersDeprecationBannerProps): {
    title: string
    body: string
    actionLabel: string
    to: string
    dataAttr: string
} {
    if (migratedToEvaluationId) {
        return {
            title: 'This tagger is now an evaluation',
            body: "The evaluation keeps this tagger's name, filters, sampling, and model. New results go there, and the tags this tagger already sent stay here.",
            actionLabel: 'Open evaluation',
            to: urls.aiObservabilityEvaluation(migratedToEvaluationId),
            dataAttr: 'taggers-deprecation-banner-open-evaluation',
        }
    }
    if (someMigrated) {
        return {
            title: 'Taggers are deprecated, and some of yours are now evaluations',
            body: 'Taggers marked "Moved to evaluation" run as evaluations with a categorical output, and the tags they already sent stay here. To tag new generations, create an evaluation with a categorical output.',
            actionLabel: 'Go to evaluations',
            to: urls.aiObservabilityEvaluations(),
            dataAttr: 'taggers-deprecation-banner-go-to-evaluations',
        }
    }
    return {
        title: 'Taggers are deprecated in favor of evaluations',
        body: 'To tag new generations, create an evaluation with a categorical output.',
        actionLabel: 'Create categorical evaluation',
        to: urls.aiObservabilityEvaluationTemplates(),
        dataAttr: 'taggers-deprecation-banner-create-evaluation',
    }
}

export function TaggersDeprecationBanner(props: TaggersDeprecationBannerProps): JSX.Element {
    const { title, body, actionLabel, to, dataAttr } = bannerContent(props)
    return (
        <LemonBanner
            type={props.migratedToEvaluationId || props.someMigrated ? 'info' : 'warning'}
            // The banner is a size container, so the hog only takes text width when there is room for it.
            icon={<HedgehogTownCrier className="hidden @lg:block w-12 h-12 shrink-0" />}
            action={{ children: actionLabel, to, 'data-attr': dataAttr }}
        >
            <p className="font-semibold">{title}</p>
            <p>{body}</p>
        </LemonBanner>
    )
}
