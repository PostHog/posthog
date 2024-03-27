export interface Theme {
    id: string
    name: string
    dark?: boolean
    sidebarStyle?: React.CSSProperties
    mainStyle?: React.CSSProperties
    boxStyle?: React.CSSProperties
}

export const themes: Theme[] = [
    {
        id: 'bleachedTom',
        name: 'Hi, My name is Tom, and I am the light.',
        dark: false,
        sidebarStyle: {
            background:
                'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7)),url(https://www.shutterstock.com/image-photo/soft-wave-blue-ocean-on-600nw-396969259.jpg)',
        },
        mainStyle: {
            background:
                'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7)),url(https://pbs.twimg.com/profile_images/1237550450/mstom_400x400.jpg)',
        },
        boxStyle: {
            background: 'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7))',
        },
    },
]
