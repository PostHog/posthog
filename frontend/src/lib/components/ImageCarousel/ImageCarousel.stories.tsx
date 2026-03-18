import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { ImageCarousel } from './ImageCarousel'

type Story = StoryObj<typeof ImageCarousel>
const meta: Meta<typeof ImageCarousel> = {
    title: 'Lemon UI/Image Carousel',
    component: ImageCarousel,
    tags: ['autodocs'],
}
export default meta

const sampleImages = [
    'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2UwZjJmZSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiMzMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiPlNjcmVlbnNob3QgMTwvdGV4dD48L3N2Zz4=',
    'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2ZlZTJlMiIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiMzMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiPlNjcmVlbnNob3QgMjwvdGV4dD48L3N2Zz4=',
    'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNjAwIiBoZWlnaHQ9IjQwMCIgZmlsbD0iI2UwZmVlOCIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMjQiIGZpbGw9IiMzMzMiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGRvbWluYW50LWJhc2VsaW5lPSJtaWRkbGUiPlNjcmVlbnNob3QgMzwvdGV4dD48L3N2Zz4=',
]

const BasicTemplate: StoryFn<typeof ImageCarousel> = (args) => {
    return <ImageCarousel {...args} />
}

export const MultipleImages: Story = BasicTemplate.bind({})
MultipleImages.args = {
    imageUrls: sampleImages,
}

export const SingleImage: Story = BasicTemplate.bind({})
SingleImage.args = {
    imageUrls: [sampleImages[0]],
}

const WithDeleteTemplate: StoryFn<typeof ImageCarousel> = () => {
    const [images, setImages] = useState(sampleImages)

    return (
        <ImageCarousel
            imageUrls={images}
            onDelete={(url) => {
                setImages(images.filter((img) => img !== url))
            }}
        />
    )
}

export const WithDelete: Story = WithDeleteTemplate.bind({})
WithDelete.args = {}

export const Empty: Story = BasicTemplate.bind({})
Empty.args = {
    imageUrls: [],
}
Empty.tags = ['test-skip']

export const Loading: Story = BasicTemplate.bind({})
Loading.args = {
    imageUrls: sampleImages,
    loading: true,
}
Loading.tags = ['test-skip']
