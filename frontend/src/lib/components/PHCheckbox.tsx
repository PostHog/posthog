import React from 'react'

interface Props {
    checked: boolean
    onChange: () => void
    color: string
}

export const PHCheckbox = ({ checked, color = 'blue', ...props }: Props): JSX.Element => (
    <div
        style={{
            display: 'inline-block',
            verticalAlign: 'middle',
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
            onClick={props.onChange}
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
