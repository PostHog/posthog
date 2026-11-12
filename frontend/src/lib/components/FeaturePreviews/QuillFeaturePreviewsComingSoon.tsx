import { useActions, useValues } from 'kea'

import {
    Button,
    Card,
    CardContent,
    CardFooter,
    CardHeader,
    CardTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { IconLink } from 'lib/lemon-ui/icons'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'
import { QuillConceptWaitlistCTA } from './QuillConceptWaitlistCTA'
import { QuillFeaturePreviewImage } from './QuillFeaturePreviewImage'

export interface QuillFeaturePreviewsComingSoonProps {
    /** Concept features that match the search. */
    features: EnrichedEarlyAccessFeature[]
}

export function QuillFeaturePreviewsComingSoon({ features }: QuillFeaturePreviewsComingSoonProps): JSX.Element {
    const { rawEarlyAccessFeaturesLoading, searchTerm } = useValues(featurePreviewsLogic)
    const { copyExternalFeaturePreviewLink } = useActions(featurePreviewsLogic)

    return (
        <div data-quill className="@container flex flex-col gap-3">
            {rawEarlyAccessFeaturesLoading ? (
                <div className="grid grid-cols-1 gap-3 @xl:grid-cols-2">
                    {[0, 1].map((index) => (
                        <Skeleton key={index} className="h-36 rounded-lg" />
                    ))}
                </div>
            ) : features.length === 0 ? (
                <Empty>
                    {searchTerm.trim() ? (
                        <EmptyHeader>
                            <EmptyTitle>No matching upcoming features</EmptyTitle>
                            <EmptyDescription>Try a different search term.</EmptyDescription>
                        </EmptyHeader>
                    ) : (
                        <EmptyHeader>
                            <EmptyTitle>Nothing coming soon right now</EmptyTitle>
                            <EmptyDescription>
                                Features we plan to build show here before you can try them.
                            </EmptyDescription>
                        </EmptyHeader>
                    )}
                </Empty>
            ) : (
                <div className="grid grid-cols-1 gap-3 @xl:grid-cols-2">
                    {features.map((feature) => (
                        <Card key={feature.flagKey} id={feature.flagKey} size="sm">
                            {feature.imageUrl && <QuillFeaturePreviewImage feature={feature} className="mx-3 h-32" />}
                            <CardHeader>
                                <CardTitle>{feature.name}</CardTitle>
                            </CardHeader>
                            <CardContent className="flex-1">
                                <Text
                                    size="xs"
                                    variant={feature.description ? 'default' : 'muted'}
                                    render={<p />}
                                    className="m-0"
                                >
                                    {feature.description || 'No description'}
                                </Text>
                            </CardContent>
                            <CardFooter className="flex flex-wrap items-center gap-1">
                                <QuillConceptWaitlistCTA feature={feature} />
                                <Button
                                    size="icon"
                                    className="ms-auto"
                                    aria-label="Copy link to this feature"
                                    tooltip="Copy link to this feature"
                                    onClick={() => copyExternalFeaturePreviewLink(feature.flagKey)}
                                >
                                    <IconLink />
                                </Button>
                            </CardFooter>
                        </Card>
                    ))}
                </div>
            )}
        </div>
    )
}
