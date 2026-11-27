import { LemonBanner, Link } from '@posthog/lemon-ui'
import { Button, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { QuillSettingsSubsection } from '../../components/QuillSettingsSubsection/QuillSettingsSubsection'
import { LearnFromSupportCard } from './LearnFromSupportCard'

export function LearnFromSupportSection(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-6">
                <Item tone="info" size="sm" className="max-w-200">
                    <ItemContent>
                        <ItemDescription>
                            Add your documents, links, and general context to{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.businessKnowledge()} target="_blank" />}
                            >
                                Business knowledge
                            </Button>{' '}
                            so the AI can ground its replies in your company's information.
                        </ItemDescription>
                    </ItemContent>
                </Item>
                <QuillSettingsSubsection
                    title="Learn from support"
                    description="When on, PostHog learns reusable answers from public human replies on resolved support tickets."
                >
                    <LearnFromSupportCard />
                </QuillSettingsSubsection>
            </div>
        )
    }

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
