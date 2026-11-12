import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { userLogic } from 'scenes/userLogic'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'
import { FEATURE_PREVIEW_WARNINGS } from './featurePreviewWarnings'
import { QuillFeaturePreviewCard } from './QuillFeaturePreviewCard'
import { QuillFeaturePreviewGroup } from './QuillFeaturePreviewGroup'

const STAGE_GROUPS = [
    {
        stage: 'beta',
        title: 'Beta',
        description: 'Close to release. These work well, and we are still polishing them.',
    },
    { stage: 'alpha', title: 'Alpha', description: 'Early versions. Expect rough edges and changes.' },
]

export interface QuillFeaturePreviewsProps {
    /** Alpha and beta features that match the search. */
    features: EnrichedEarlyAccessFeature[]
    failedToLoad: boolean
    flagsHonored: boolean
}

export function QuillFeaturePreviews({ features, failedToLoad, flagsHonored }: QuillFeaturePreviewsProps): JSX.Element {
    const { rawEarlyAccessFeaturesLoading, searchTerm } = useValues(featurePreviewsLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { setSearchTerm } = useActions(featurePreviewsLogic)

    const isSearching = !!searchTerm.trim()
    const enabledCount = features.filter((feature) => feature.enabled).length

    return (
        <div data-quill className="@container flex flex-col gap-4">
            {!flagsHonored && features.length > 0 && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            Feature previews on this instance are controlled by the PERSISTED_FEATURE_FLAGS environment
                            variable, not the toggles below.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}
            {failedToLoad && (
                <Item tone="warning" size="sm">
                    <ItemContent>
                        <ItemDescription>
                            We couldn't load our internal feature flags. An ad blocker or a network issue can cause
                            this. If you use feature flags in your own app, a{' '}
                            <Button
                                variant="link"
                                size="inline"
                                render={<LinkPrimitive to="https://posthog.com/docs/advanced/proxy" target="_blank" />}
                            >
                                reverse proxy
                            </Button>{' '}
                            prevents this for your users.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}
            {rawEarlyAccessFeaturesLoading ? (
                <div className="grid grid-cols-1 gap-3 @2xl:grid-cols-2">
                    {[0, 1, 2, 3].map((index) => (
                        <Skeleton key={index} className="h-48 rounded-lg" />
                    ))}
                </div>
            ) : features.length === 0 && !isSearching ? (
                failedToLoad ? null : (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>No feature previews right now</EmptyTitle>
                            <EmptyDescription>New previews show here when they are ready to try.</EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                )
            ) : (
                <>
                    <div className="flex flex-wrap items-center gap-2">
                        <InputGroup size="sm" className="max-w-80 flex-1">
                            <InputGroupAddon align="inline-start">
                                <IconSearch />
                            </InputGroupAddon>
                            <InputGroupInput
                                type="search"
                                placeholder="Search feature previews..."
                                aria-label="Search feature previews"
                                value={searchTerm}
                                onChange={(event) => setSearchTerm(event.target.value)}
                            />
                        </InputGroup>
                        {!isSearching && (
                            <Text size="xs" variant="muted" render={<span />} className="m-0" translate="no">
                                {`${enabledCount} of ${features.length} on`}
                            </Text>
                        )}
                    </div>
                    {features.length === 0 ? (
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>No matching feature previews</EmptyTitle>
                                <EmptyDescription>Try a different search term.</EmptyDescription>
                            </EmptyHeader>
                            <EmptyContent>
                                <Button variant="outline" onClick={() => setSearchTerm('')}>
                                    Clear search
                                </Button>
                            </EmptyContent>
                        </Empty>
                    ) : (
                        STAGE_GROUPS.map(({ stage, title, description }) => {
                            const groupFeatures = features.filter((feature) => feature.stage === stage)
                            return groupFeatures.length === 0 ? null : (
                                <QuillFeaturePreviewGroup
                                    key={stage}
                                    title={title}
                                    description={description}
                                    count={groupFeatures.length}
                                >
                                    <div className="grid grid-cols-1 gap-3 @xl:grid-cols-2">
                                        {groupFeatures.map((feature) => (
                                            <QuillFeaturePreviewCard
                                                key={feature.flagKey}
                                                feature={feature}
                                                flagsHonored={flagsHonored}
                                                warning={FEATURE_PREVIEW_WARNINGS[feature.flagKey]?.resolve(
                                                    hasAvailableFeature
                                                )}
                                            />
                                        ))}
                                    </div>
                                </QuillFeaturePreviewGroup>
                            )
                        })
                    )}
                </>
            )}
        </div>
    )
}
