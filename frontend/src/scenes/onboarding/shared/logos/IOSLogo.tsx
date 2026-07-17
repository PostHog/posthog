import React from 'react'

export const IOSLogo = React.memo(function IOSLogo(): JSX.Element {
    return (
        <svg className="h-8 w-8" fill="none" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 21 24">
            <title>iOS logo</title>
            <path
                d="M16.844 23.016c-1.3 1.262-2.736 1.066-4.104.47-1.454-.607-2.784-.645-4.32 0-1.913.826-2.928.586-4.08-.47C-2.164 16.32-1.204 6.12 6.188 5.736c1.793.096 3.048.991 4.104 1.066 1.57-.32 3.072-1.234 4.752-1.114 2.018.163 3.528.96 4.536 2.393-4.152 2.496-3.168 7.968.646 9.504-.764 2.004-1.743 3.984-3.384 5.448l.002-.017zM10.148 5.664C9.954 2.688 12.366.24 15.14 0c.382 3.432-3.12 6-4.992 5.664z"
                fill="#000"
                className="dark:fill-white"
            />
        </svg>
    )
})
