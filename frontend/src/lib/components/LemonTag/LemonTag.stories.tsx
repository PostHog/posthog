import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonTag, LemonTagProps, LemonTagTypes } from 'lib/components/LemonTag/LemonTag'

export default {
    title: 'Lemon UI/Lemon Tag',
    component: LemonTag,
    argTypes: {},
} as ComponentMeta<typeof LemonTag>

const BasicTemplate: ComponentStory<typeof LemonTag> = (props: LemonTagProps) => {
    return (
        <div className="flex flex-row gap-4">
            {LemonTagTypes.map((tagType, i) => (
                <LemonTag key={i} type={tagType} {...props} />
            ))}
        </div>
    )
}

export const Default = BasicTemplate.bind({})
Default.args = {
    onClose: null as any,
}

// export const ComplexContent = BasicTemplate.bind({})
// ComplexContent.args = {
//     children: (
//         <span className="flex gap-2 items-center">
//             <ProfilePicture email="ben@posthog.com" size="sm" />
//             <span>
//                 Look at me I'm <b>bold!</b>
//             </span>
//         </span>
//     ),
//     onClose: () => alert('Close clicked!'),
// }
