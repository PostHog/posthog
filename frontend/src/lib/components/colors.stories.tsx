import * as React from 'react'
import { Meta } from '@storybook/react'
import { Popup } from './Popup/Popup'
import { useState } from 'react'

export default {
    title: 'Lemon UI/Colors',
    parameters: {
        options: { showPanel: false },
        docs: {
            description: {
                component: 'Colors can be used in a variety of ways',
            },
        },
    },
} as Meta

const colorGroups = {
    primary: ['primary-highlight', 'primary-light', 'primary', 'primary-dark'],
    danger: ['danger-highlight', 'danger-light', 'danger', 'danger-dark'],
    warning: ['warning-highlight', 'warning-light', 'warning', 'warning-dark'],
    success: ['success-highlight', 'success-light', 'success', 'success-dark'],
    'primary-alt': ['primary-alt-highlight', 'primary-alt', 'primary-alt-dark'],
    'default (primary text)': ['default', 'default-dark'],
    'muted (secondary text)': ['muted', 'muted-dark'],
    'muted-alt ': ['muted-alt', 'muted-alt-dark'],
    border: ['border', 'border-light', 'border-dark', 'border-active'],
    light: ['white', 'light'],
}

export function ColorPalette(): JSX.Element {
    const [hover, setHover] = useState<string>()
    return (
        <div className="flex gap-4 flex-wrap items-start">
            {Object.keys(colorGroups).map((group) => (
                <div key={group} className="flex flex-col" style={{ width: 150, height: 200 }}>
                    <div className="font-bold text-ellipsis mb-2">{group}</div>
                    <div className="rounded-lg overflow-hidden flex flex-col flex-1">
                        {colorGroups[group].map((color: string) => (
                            <Popup
                                key={color}
                                visible={hover === color}
                                placement="right"
                                overlay={
                                    <>
                                        <h3>{color}</h3>
                                    </>
                                }
                            >
                                <div className={`bg-${color} flex-1`} onMouseEnter={() => setHover(color)} />
                            </Popup>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    )
}
