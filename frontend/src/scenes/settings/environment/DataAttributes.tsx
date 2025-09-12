import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { teamLogic } from 'scenes/teamLogic'

export function DataAttributes(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [value, setValue] = useState([] as string[])

    useEffect(() => setValue(currentTeam?.data_attributes || []), [currentTeam])

    if (!currentTeam) {
        return <LemonSkeleton />
    }

    return (
        <>
            <p>
                Specify a list of{' '}
                <Link to="https://developer.mozilla.org/en-US/docs/Learn/HTML/Howto/Use_data_attributes">
                    data attributes
                </Link>{' '}
                used in your app. For example: <code>data-attr, data-custom-id, data-myref-*</code>. These attributes
                will be used when using the toolbar and defining actions to match unique elements on your pages. You can
                use <code>*</code> as a wildcard.
            </p>
            <p>
                For example, when creating an action on your CTA button, the best selector could be something like:{' '}
                <code>div &gt; form &gt; button:nth-child(2)</code>. However all buttons in your app have a{' '}
                <code>data-custom-id</code> attribute. If you allow it here, the selector for your button will instead
                be <code>button[data-custom-id='cta-button']</code>.
            </p>
            <div className="deprecated-space-y-4 max-w-160">
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    onChange={(values: string[]) => setValue(values || [])}
                    value={value}
                    data-attr="data-attribute-select"
                    placeholder="data-attr, ..."
                    loading={currentTeamLoading}
                    disabled={currentTeamLoading}
                />
                <LemonButton
                    type="primary"
                    onClick={() =>
                        updateCurrentTeam({ data_attributes: value.map((s) => s.trim()).filter((a) => a) || [] })
                    }
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
