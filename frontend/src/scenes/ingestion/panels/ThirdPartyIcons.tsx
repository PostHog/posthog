import React from 'react'

export const Segment = (props: React.SVGProps<SVGSVGElement>): JSX.Element => {
    return (
        <svg {...props} width="30" height="30" fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 23">
            <mask id="a" maskUnits="userSpaceOnUse" x="0" y="12" width="23" height="11">
                <path d="M22.704 22.262H0v-9.348h22.704v9.348z" fill="#fff" />
            </mask>
            <g mask="url(#a)" fillRule="evenodd" clipRule="evenodd">
                <path d="M14.96 15.22H1.153a1.152 1.152 0 110-2.305h13.809a1.152 1.152 0 110 2.305z" fill="#93C8A2" />
                <path
                    d="M12 22.28c-1.125 0-2.236-.168-3.302-.498a1.153 1.153 0 01.683-2.202 8.825 8.825 0 002.62.394c3.91 0 7.305-2.51 8.449-6.246a1.152 1.152 0 012.204.674A11.081 11.081 0 0112 22.28z"
                    fill="#43AF79"
                />
            </g>
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M22.848 9.364H9.04a1.152 1.152 0 110-2.304h13.808a1.152 1.152 0 110 2.304z"
                fill="#93C8A2"
            />
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M2.449 9.365a1.153 1.153 0 01-1.102-1.49A11.08 11.08 0 0112 0c1.126 0 2.236.167 3.302.498a1.152 1.152 0 11-.683 2.201A8.915 8.915 0 0012 2.308a8.787 8.787 0 00-8.448 6.246 1.153 1.153 0 01-1.102.815"
                fill="#43AF79"
            />
            <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M19.993 3.82a1.152 1.152 0 11-2.304.001 1.152 1.152 0 012.304 0zM6.312 18.46a1.152 1.152 0 11-2.304.001 1.152 1.152 0 012.304 0z"
                fill="#93C8A2"
            />
        </svg>
    )
}
