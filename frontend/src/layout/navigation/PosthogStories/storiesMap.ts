export interface story {
    id: string
    title: string
    thumbnailUrl: string
    description?: string
    mediaUrl: string
    type: 'image' | 'video'
    link?: string
    order: number
}

export interface storyGroup {
    id: string
    title: string
    stories: story[]
    order: number
}

export const storiesMap: storyGroup[] = [
    {
        id: 'last_features',
        title: 'Last Features',
        stories: [
            {
                id: '1',
                title: 'Story 01',
                thumbnailUrl: 'https://picsum.photos/id/1011/200/300',
                description: 'Story 1 description',
                mediaUrl: 'https://res.cloudinary.com/dmukukwp6/video/upload/test_vid_b7ad3c1a59.mp4',
                type: 'video',
                link: 'https://picsum.photos/id/1011/400/600',
                order: 1,
            },
            {
                id: '2',
                title: 'Story 02',
                thumbnailUrl: 'https://picsum.photos/id/1012/200/300',
                description: 'Story 2 description',
                mediaUrl: 'https://picsum.photos/id/1012/400/600',
                type: 'image',
                link: 'https://picsum.photos/id/1012/400/600',
                order: 2,
            },
        ],
        order: 1,
    },
    {
        id: 'toolbar',
        title: 'Toolbar',
        stories: [
            {
                id: '1',
                title: 'Story 11',
                thumbnailUrl: 'https://picsum.photos/id/1025/200/300',
                description: 'Story 1 description',
                mediaUrl: 'https://picsum.photos/id/1025/400/600',
                type: 'image',
                link: 'https://picsum.photos/id/1025/400/600',
                order: 1,
            },
            {
                id: '2',
                title: 'Story 12',
                thumbnailUrl: 'https://picsum.photos/id/1035/200/300',
                description: 'Story 2 description',
                mediaUrl: 'https://picsum.photos/id/1035/400/600',
                type: 'image',
                link: 'https://picsum.photos/id/1035/400/600',
                order: 2,
            },
            {
                id: '3',
                title: 'Story 13',
                thumbnailUrl: 'https://picsum.photos/id/1041/200/300',
                description: 'Story 3 description',
                mediaUrl: 'https://picsum.photos/id/1041/400/600',
                type: 'image',
                link: 'https://picsum.photos/id/1041/400/600',
                order: 3,
            },
        ],
        order: 2,
    },
]
