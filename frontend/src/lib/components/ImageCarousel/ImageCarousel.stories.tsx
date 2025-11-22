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
    'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=600&h=400&fit=crop',
    'https://images.unsplash.com/photo-1469474968028-56623f02e42e?w=400&h=600&fit=crop',
    'https://images.unsplash.com/photo-1447752875215-b2761acb3c5d?w=400&h=400&fit=crop',
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

export const Loading: Story = BasicTemplate.bind({})
Loading.args = {
    imageUrls: sampleImages,
    loading: true,
}
