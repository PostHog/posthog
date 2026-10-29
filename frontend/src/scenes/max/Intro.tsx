import { useValues } from 'kea'

import { Heading, Text } from '@posthog/quill'

import { Logomark } from 'lib/brand'

import { useThreadSkin } from 'products/posthog_ai/frontend/api/logics'

import { AILiabilityNotice } from './components/AILiabilityNotice'
import { MaxChangelog } from './components/MaxChangelog'
import { maxLogic } from './maxLogic'

export function Intro({
    forceHeadline,
    forceSubheadline,
}: {
    forceHeadline?: string
    forceSubheadline?: string | null
}): JSX.Element {
    const { headline } = useValues(maxLogic)
    const skin = useThreadSkin()
    const headlineToUse = forceHeadline || headline
    const subheadlineToUse = forceSubheadline === null ? null : forceSubheadline || 'Build something people want.'

    return (
        <>
            <div className="flex p-2">
                <Logomark jumpOnClick size="md" />
            </div>
            {skin === 'quill' ? (
                <div data-quill className="mb-1 flex flex-col items-center gap-2 text-center">
                    <Heading size="xl" render={<h2 className="m-0 text-balance @2xl/main-content:text-2xl" />}>
                        {headlineToUse}
                    </Heading>
                    {subheadlineToUse && (
                        <Text size="sm" variant="muted" className="m-0 italic text-pretty">
                            {subheadlineToUse}
                        </Text>
                    )}
                </div>
            ) : (
                <div className="text-center mb-1">
                    <h2 className="text-xl @2xl/main-content:text-2xl font-bold mb-2 text-balance">{headlineToUse}</h2>
                    {subheadlineToUse && (
                        <div className="text-sm italic text-tertiary text-pretty py-0.5">{subheadlineToUse}</div>
                    )}
                </div>
            )}
            {/* The notice and the changelog stay lemon banners in the quill skin until they get one of their own. */}
            <AILiabilityNotice />
            <MaxChangelog />
        </>
    )
}
