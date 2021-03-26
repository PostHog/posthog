import { Button, Input, Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import React, { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

export function DataAttributes(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { patchCurrentTeam } = useActions(teamLogic)
    const [value, setValue] = useState(currentTeam?.important_data_attributes?.join(', ') || '')

    if (!currentTeam) {
        return <Skeleton paragraph={{ rows: 0 }} active />
    }

    return (
        <>
            <p>
                Specify a comma-separated list of{' '}
                <a
                    href="https://developer.mozilla.org/en-US/docs/Learn/HTML/Howto/Use_data_attributes"
                    rel="noreferrer noopener"
                >
                    data attributes
                </a>{' '}
                used in your app. For example: <code>data-attr, data-custom-id, data-myref</code>. These attributes will
                be used when creating actions to match unique elements on your pages.
            </p>
            <p>
                For example, when creating an action on your CTA button, the best selector could be something like:{' '}
                <code>div &gt; form &gt; button</code>. However all buttons in your app have a{' '}
                <code>data-custom-id</code> attribute. If you whitelist it here, the selector for your button will
                instead be <code>button[data-custom-id='cta-button']</code>.
            </p>
            <div>
                <Input
                    placeholder="data-attr, ..."
                    style={{ width: '20rem', maxWidth: '100%' }}
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                />
                <Button
                    type="primary"
                    onClick={() =>
                        patchCurrentTeam({
                            important_data_attributes:
                                value
                                    .split(',')
                                    .map((s) => s.trim())
                                    .filter((a) => a) || [],
                        })
                    }
                >
                    Update
                </Button>
            </div>
        </>
    )
}
