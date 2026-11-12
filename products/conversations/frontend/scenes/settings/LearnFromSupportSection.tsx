import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { LearnFromSupportCard } from './LearnFromSupportCard'

export function LearnFromSupportSection(): JSX.Element {
    return (
        <>
            <LemonBanner type="info" className="max-w-[800px] mt-3">
                Add your documents, links, and general context to{' '}
                <Link to={urls.businessKnowledge()} target="_blank">
                    Business knowledge
                </Link>{' '}
                so the AI can ground its replies in your company's information.
            </LemonBanner>
            <SceneSection
                title="Learn from support"
                titleSize="sm"
                className="my-8"
                description="When on, PostHog learns reusable answers from public human replies on resolved support tickets."
            >
                <LearnFromSupportCard />
            </SceneSection>
        </>
    )
}
