import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

// pinned: localStorage dismiss key shared with the LemonBanner in ApprovalPolicies. Renaming shows the notice again.
const DISMISS_KEY = 'approval-policies-experiment-split'

export function QuillExperimentPoliciesNotice(): JSX.Element | null {
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: DISMISS_KEY }))
    const { dismiss } = useActions(lemonBannerLogic({ dismissKey: DISMISS_KEY }))

    if (isDismissed) {
        return null
    }

    return (
        <Item tone="info" size="sm">
            <ItemContent>
                <ItemTitle>Experiments now have their own approval policies</ItemTitle>
                <ItemDescription>
                    Launching, pausing, and changing the rollout or variant split of an experiment now follow the
                    experiment policies. Feature flag policies cover the flags that no product manages, so flags that a
                    survey, product tour, or early access feature manages no longer need approval. Surveys will get
                    their own policies soon.{' '}
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={
                            <LinkPrimitive
                                to="https://posthog.com/docs/settings/approvals#experiment-policies"
                                target="_blank"
                            />
                        }
                    >
                        Learn how policies apply to each flag
                    </Button>
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button size="icon" aria-label="Dismiss" tooltip="Dismiss" onClick={dismiss}>
                    <IconX />
                </Button>
            </ItemActions>
        </Item>
    )
}
