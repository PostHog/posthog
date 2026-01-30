import React from 'react'

export const PydanticAILogo = React.memo(function PydanticAILogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" viewBox="0 0 256 256" fill="none" xmlns="http://www.w3.org/2000/svg">
            <title>Pydantic AI logo</title>
            <path
                d="M128 16L32 72v112l96 56 96-56V72L128 16zm0 16l80 46.7V176L128 224l-80-48V78.7L128 32z"
                fill="#E6007A"
            />
            <path
                d="M128 80l-48 28v56l48 28 48-28v-56l-48-28zm0 16l32 18.7v37.3L128 176l-32-24V114.7L128 96z"
                fill="#E6007A"
            />
        </svg>
    )
})
