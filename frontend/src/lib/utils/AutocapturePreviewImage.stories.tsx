import { Meta, StoryFn } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { ElementType } from '~/types'

import { AutocaptureImageTab, AutocapturePreviewImage } from './autocapture-previews'

const meta: Meta = {
    title: 'Utils/Autocapture Preview Image',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        testOptions: {
            allowImagesWithoutWidth: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}

const imagePath = '/id/237/200/300.jpg?hmac=TmmQSbShHz9CdQm0NkEjx1Dyh_Y984R9LpNrpvH2D_U'
const imageOrigin = 'https://fastly.picsum.photos'
const imageWidth = '200'
const imageHeight = '300'

export default meta

// Mock data for different scenarios
const mockElementsNoImage: ElementType[] = [
    {
        tag_name: 'div',
        attributes: { attr__class: 'some-class' },
    },
    {
        tag_name: 'button',
        attributes: { attr__id: 'submit-btn' },
    },
]

const mockElementsWithAbsoluteImage: ElementType[] = [
    {
        tag_name: 'img',
        attributes: {
            attr__src: `${imageOrigin}${imagePath}`,
            attr__width: imageWidth,
            attr__height: imageHeight,
        },
    },
]

const mockElementsWithRelativeImage: ElementType[] = [
    {
        tag_name: 'img',
        attributes: {
            attr__src: imagePath,
            attr__width: imageWidth,
            attr__height: imageHeight,
        },
    },
]

const mockPropertiesWithCurrentUrl = {
    $current_url: `${imageOrigin}/website-page/path`,
    other_prop: 'value',
}

const mockPropertiesNoCurrentUrl = {
    other_prop: 'value',
    some_data: 123,
}

// Stories for AutocapturePreviewImage
export const NoImage: StoryFn = () => (
    <div className="p-4">
        <h3>No Image Elements</h3>
        <AutocapturePreviewImage elements={mockElementsNoImage} />
        <p className="text-muted-foreground mt-2 text-sm">Should render null (nothing shown)</p>
    </div>
)

export const AbsoluteImageUrl: StoryFn = () => (
    <div className="p-4">
        <h3>Absolute Image URL</h3>
        <AutocapturePreviewImage elements={mockElementsWithAbsoluteImage} />
        <p className="text-muted-foreground mt-2 text-sm">Should show image with tooltip</p>
    </div>
)

export const RelativeImageWithCurrentUrl: StoryFn = () => (
    <div className="p-4">
        <h3>Relative Image with Current URL</h3>
        <AutocapturePreviewImage elements={mockElementsWithRelativeImage} properties={mockPropertiesWithCurrentUrl} />
        <p className="text-muted-foreground mt-2 text-sm">Should show image (relative URL converted to absolute)</p>
    </div>
)

export const RelativeImageNoCurrentUrl: StoryFn = () => (
    <div className="p-4">
        <h3>Relative Image without Current URL</h3>
        <AutocapturePreviewImage elements={mockElementsWithRelativeImage} properties={mockPropertiesNoCurrentUrl} />
        <p className="text-muted-foreground mt-2 text-sm">Should show image with relative path (may fail to load)</p>
    </div>
)

export const RelativeImageNoProperties: StoryFn = () => (
    <div className="p-4">
        <h3>Relative Image without Properties</h3>
        <AutocapturePreviewImage elements={mockElementsWithRelativeImage} />
        <p className="text-muted-foreground mt-2 text-sm">Should show image with relative path (may fail to load)</p>
    </div>
)

// Stories for AutocaptureImageTab
export const TabNoImage: StoryFn = () => (
    <div className="p-4">
        <h3>Tab: No Image Elements</h3>
        <AutocaptureImageTab elements={mockElementsNoImage} />
        <p className="text-muted-foreground mt-2 text-sm">Should render null (nothing shown)</p>
    </div>
)

export const TabAbsoluteImageUrl: StoryFn = () => (
    <div className="p-4">
        <h3>Tab: Absolute Image URL</h3>
        <AutocaptureImageTab elements={mockElementsWithAbsoluteImage} />
        <p className="text-muted-foreground mt-2 text-sm">Should show full-width image in tab container</p>
    </div>
)

export const TabRelativeImageWithCurrentUrl: StoryFn = () => (
    <div className="p-4">
        <h3>Tab: Relative Image with Current URL</h3>
        <AutocaptureImageTab elements={mockElementsWithRelativeImage} properties={mockPropertiesWithCurrentUrl} />
        <p className="text-muted-foreground mt-2 text-sm">
            Should show full-width image (relative URL converted to absolute)
        </p>
    </div>
)

export const TabRelativeImageNoCurrentUrl: StoryFn = () => (
    <div className="p-4">
        <h3>Tab: Relative Image without Current URL</h3>
        <AutocaptureImageTab elements={mockElementsWithRelativeImage} properties={mockPropertiesNoCurrentUrl} />
        <p className="text-muted-foreground mt-2 text-sm">
            Should show full-width image with relative path (may fail to load)
        </p>
    </div>
)

export const TabRelativeImageNoProperties: StoryFn = () => (
    <div className="p-4">
        <h3>Tab: Relative Image without Properties</h3>
        <AutocaptureImageTab elements={mockElementsWithRelativeImage} />
        <p className="text-muted-foreground mt-2 text-sm">
            Should show full-width image with relative path (may fail to load)
        </p>
    </div>
)

// Combined comparison story
export const AllScenarios: StoryFn = () => (
    <div className="space-y-8 p-4">
        <div>
            <h2 className="mb-4 text-xl font-bold">AutocapturePreviewImage Component</h2>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                <div className="rounded border p-4">
                    <h4>No Image</h4>
                    <AutocapturePreviewImage elements={mockElementsNoImage} />
                </div>
                <div className="rounded border p-4">
                    <h4>Absolute URL</h4>
                    <AutocapturePreviewImage elements={mockElementsWithAbsoluteImage} />
                </div>
                <div className="rounded border p-4">
                    <h4>Relative + Current URL</h4>
                    <AutocapturePreviewImage
                        elements={mockElementsWithRelativeImage}
                        properties={mockPropertiesWithCurrentUrl}
                    />
                </div>
                <div className="rounded border p-4">
                    <h4>Relative, No Current URL</h4>
                    <AutocapturePreviewImage
                        elements={mockElementsWithRelativeImage}
                        properties={mockPropertiesNoCurrentUrl}
                    />
                </div>
                <div className="rounded border p-4">
                    <h4>Relative, No Properties</h4>
                    <AutocapturePreviewImage elements={mockElementsWithRelativeImage} />
                </div>
            </div>
        </div>

        <div>
            <h2 className="mb-4 text-xl font-bold">AutocaptureImageTab Component</h2>
            <div className="space-y-4">
                <div className="rounded border">
                    <h4 className="bg-gray-50 p-2">No Image</h4>
                    <AutocaptureImageTab elements={mockElementsNoImage} />
                </div>
                <div className="rounded border">
                    <h4 className="bg-gray-50 p-2">Absolute URL</h4>
                    <AutocaptureImageTab elements={mockElementsWithAbsoluteImage} />
                </div>
                <div className="rounded border">
                    <h4 className="bg-gray-50 p-2">Relative + Current URL</h4>
                    <AutocaptureImageTab
                        elements={mockElementsWithRelativeImage}
                        properties={mockPropertiesWithCurrentUrl}
                    />
                </div>
                <div className="rounded border">
                    <h4 className="bg-gray-50 p-2">Relative, No Current URL</h4>
                    <AutocaptureImageTab
                        elements={mockElementsWithRelativeImage}
                        properties={mockPropertiesNoCurrentUrl}
                    />
                </div>
                <div className="rounded border">
                    <h4 className="bg-gray-50 p-2">Relative, No Properties</h4>
                    <AutocaptureImageTab elements={mockElementsWithRelativeImage} />
                </div>
            </div>
        </div>
    </div>
)
