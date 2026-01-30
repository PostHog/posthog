import React from 'react'

export const CrewAILogo = React.memo(function CrewAILogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" viewBox="0 0 256 256" fill="none" xmlns="http://www.w3.org/2000/svg">
            <title>CrewAI logo</title>
            <path
                d="M128 32c-8.8 0-16 7.2-16 16s7.2 16 16 16 16-7.2 16-16-7.2-16-16-16zM64 80c-8.8 0-16 7.2-16 16s7.2 16 16 16 16-7.2 16-16-7.2-16-16-16zM192 80c-8.8 0-16 7.2-16 16s7.2 16 16 16 16-7.2 16-16-7.2-16-16-16z"
                fill="black"
                className="dark:fill-white"
            />
            <path
                d="M128 64v32M80 100l32 20M176 100l-32 20M128 128v48M96 200c0-17.7 14.3-32 32-32s32 14.3 32 32"
                stroke="black"
                strokeWidth="8"
                strokeLinecap="round"
                className="dark:stroke-white"
            />
            <circle cx="128" cy="144" r="24" stroke="black" strokeWidth="8" fill="none" className="dark:stroke-white" />
        </svg>
    )
})
