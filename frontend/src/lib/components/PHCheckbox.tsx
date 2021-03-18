import React from 'react'

interface Props {
    checked: boolean
    onChange: () => void
    color: string
    disabled?: boolean
}

export const PHCheckbox = ({ checked, color = 'blue', disabled = false, ...props }: Props): JSX.Element => (
    <div
        style={{
            display: 'inline-block',
            verticalAlign: 'middle',
            cursor: disabled ? undefined : 'pointer',
        }}
    >
        <div
            style={{
                display: 'inline-block',
                width: '16px',
                height: '16px',
                background: checked ? color : 'lightgray',
                borderRadius: '3px',
                transition: 'all 150ms',
            }}
            onClick={!disabled ? props.onChange : () => {}}
        >
            <svg
                style={{
                    visibility: checked ? 'visible' : 'hidden',
                    fill: 'none',
                    stroke: 'white',
                    strokeWidth: '2px',
                }}
                viewBox="0 0 24 24"
            >
                <polyline points="20 6 9 17 4 12" />
            </svg>
        </div>
    </div>
)
