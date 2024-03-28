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
    {
        id: 'developers',
        name: 'Developers, Developers, Developers, Developers',
        dark: false,
        sidebarStyle: {
            background:
                'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7)),url(https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExOWM2eDhveXRrNTJrdGZ5bmdhaGJrZWNqczFiZzUzMXF5aXc5azljNSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/2yuiXIlW8TwY2raAPB/giphy-downsized-large.gif)',
        },
        mainStyle: {
            background:
                'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7)),url(https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExa3ljdm5mczV3dnQza3lqY3E1czEyd3J0d3A4ZmtqbGE3a2JybTJlMyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/l3q2zbskZp2j8wniE/giphy-downsized-large.gif)',
        },
        boxStyle: {
            background: 'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7))',
        },
    },
    {
        id: 'livelaughhog',
        name: 'Live, Laugh, Hog',
        dark: false,
        sidebarStyle: {
            background:
                'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7)), repeat url(https://i.imgur.com/okHCBbPl.png)',
        },
        mainStyle: {
            background:
                'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7)), repeat url(https://i.imgur.com/okHCBbPl.png)',
        },
        boxStyle: {
            background: 'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7))',
        },
    },
    {
        id: 'herisson',
        name: 'Live, Laugh, Hog',
        dark: false,
        mainStyle: {
            background:
                'linear-gradient(rgba(255,255,255,0.5),rgba(255,255,255,0.5)), url(https://i.imgur.com/RrGMCR6.jpeg)',
            backgroundSize: 'contain',
            backgroundPosition: 'center',
            backgroundRepeat: 'repeat',
        },
        boxStyle: {
            background: 'linear-gradient(rgba(255,255,255,0.7),rgba(255,255,255,0.7))',
        },
    },
]
