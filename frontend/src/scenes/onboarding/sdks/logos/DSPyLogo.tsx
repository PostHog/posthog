import React from 'react'

export const DSPyLogo = React.memo(function DSPyLogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" viewBox="0 0 256 256" fill="none" xmlns="http://www.w3.org/2000/svg">
            <title>DSPy logo</title>
            <path
                d="M128 24C70.6 24 24 70.6 24 128s46.6 104 104 104 104-46.6 104-104S185.4 24 128 24z"
                fill="black"
                className="dark:fill-white"
            />
            <path
                d="M72 100h32c11 0 20 9 20 20s-9 20-20 20H88v24H72V100zm16 28h16c2.2 0 4-1.8 4-4s-1.8-4-4-4H88v8zM136 100h16l20 32 20-32h16v64h-16v-36l-20 30-20-30v36h-16V100z"
                fill="white"
                className="dark:fill-black"
            />
        </svg>
    )
})
