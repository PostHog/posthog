import React from 'react'

export const InstructorLogo = React.memo(function InstructorLogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" viewBox="0 0 256 256" fill="none" xmlns="http://www.w3.org/2000/svg">
            <title>Instructor logo</title>
            <path
                d="M128 24C70.6 24 24 70.6 24 128s46.6 104 104 104 104-46.6 104-104S185.4 24 128 24zm0 16c48.6 0 88 39.4 88 88s-39.4 88-88 88-88-39.4-88-88 39.4-88 88-88z"
                fill="black"
                className="dark:fill-white"
            />
            <path
                d="M128 72c-30.9 0-56 25.1-56 56s25.1 56 56 56 56-25.1 56-56-25.1-56-56-56zm0 16c22.1 0 40 17.9 40 40s-17.9 40-40 40-40-17.9-40-40 17.9-40 40-40z"
                fill="black"
                className="dark:fill-white"
            />
            <circle cx="128" cy="128" r="16" fill="black" className="dark:fill-white" />
        </svg>
    )
})
