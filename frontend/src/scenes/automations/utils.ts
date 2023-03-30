import { Edge, Node } from 'reactflow'
import { AnyAutomationStep, AutomationEdge, AutomationStepKind } from './schema'
import { uuid } from 'lib/utils'

const emojis = [
    '🍇 Grapes',
    '🍈 Melon',
    '🍉 Watermelon',
    '🍊 Tangerine',
    '🍋 Lemon',
    '🍌 Banana',
    '🍍 Pineapple',
    '🥭 Mango',
    '🍎 Red Apple',
    '🍏 Green Apple',
    '🍐 Pear',
    '🍑 Peach',
    '🍒 Cherries',
    '🍓 Strawberry',
    '🫐 Blueberries',
    '🥝 Kiwi Fruit',
    '🍅 Tomato',
    '🫒 Olive',
    '🥥 Coconut',
    '🥑 Avocado',
    '🍆 Eggplant',
    '🥔 Potato',
    '🥕 Carrot',
    '🌽 Ear of Corn',
    '🌶️ Hot Pepper',
    '🫑 Bell Pepper',
    '🥒 Cucumber',
    '🥬 Leafy Green',
    '🥦 Broccoli',
    '🧄 Garlic',
    '🧅 Onion',
    '🍄 Mushroom',
    '🥜 Peanuts',
    '🌰 Chestnut',
    '🍞 Bread',
    '🥐 Croissant',
    '🥖 Baguette Bread',
    '🫓 Flatbread',
    '🥨 Pretzel',
    '🥯 Bagel',
    '🥞 Pancakes',
    '🧇 Waffle',
    '🧀 Cheese Wedge',
    '🍖 Meat on Bone',
    '🍗 Poultry Leg',
    '🥩 Cut of Meat',
    '🥓 Bacon',
    '🍔 Hamburger',
    '🍟 French Fries',
    '🍕 Pizza',
    '🌭 Hot Dog',
    '🥪 Sandwich',
    '🌮 Taco',
    '🌯 Burrito',
    '🫔 Tamale',
    '🥙 Stuffed Flatbread',
    '🧆 Falafel',
    '🥚 Egg',
    '🍳 Cooking',
    '🥘 Shallow Pan of Food',
    '🍲 Pot of Food',
    '🫕 Fondue',
    '🥣 Bowl with Spoon',
    '🥗 Green Salad',
    '🍿 Popcorn',
    '🧈 Butter',
    '🧂 Salt',
    '🥫 Canned Food',
    '🍱 Bento Box',
    '🍘 Rice Cracker',
    '🍙 Rice Ball',
    '🍚 Cooked Rice',
    '🍛 Curry Rice',
    '🍜 Steaming Bowl',
    '🍝 Spaghetti',
    '🍠 Roasted Sweet Potato',
    '🍢 Oden',
    '🍣 Sushi',
    '🍤 Fried Shrimp',
    '🍥 Fish Cake with Swirl',
    '🥮 Moon Cake',
    '🍡 Dango',
    '🥟 Dumpling',
    '🥠 Fortune Cookie',
    '🥡 Takeout Box',
    '🦪 Oyster',
    '🍦 Soft Ice Cream',
    '🍧 Shaved Ice',
    '🍨 Ice Cream',
    '🍩 Doughnut',
    '🍪 Cookie',
    '🎂 Birthday Cake',
    '🍰 Shortcake',
    '🧁 Cupcake',
    '🥧 Pie',
    '🍫 Chocolate Bar',
    '🍬 Candy',
    '🍭 Lollipop',
    '🍮 Custard',
    '🍯 Honey Pot',
    '🍼 Baby Bottle',
    '🥛 Glass of Milk',
    '☕ Hot Beverage',
    '🫖 Teapot',
    '🍵 Teacup Without Handle',
    '🍶 Sake',
    '🍾 Bottle with Popping Cork',
    '🍷 Wine Glass',
    '🍸 Cocktail Glass',
    '🍹 Tropical Drink',
    '🍺 Beer Mug',
    '🍻 Clinking Beer Mugs',
    '🥂 Clinking Glasses',
    '🥃 Tumbler Glass',
    '🥤 Cup with Straw',
    '🧋 Bubble Tea',
    '🧃 Beverage Box',
    '🧉 Mate',
    '🧊 Ice',
    '🥢 Chopsticks',
    '🍽️ Fork and Knife with Plate',
    '🍴 Fork and Knife',
    '🥄 Spoon',
]

export const randomLabel = (): string => {
    return emojis[~~(Math.random() * emojis.length)]
}

const SEPARATION = 150

export const stepsToFlowSteps = (steps: AnyAutomationStep[]): Node[] => {
    return steps.map((step: AnyAutomationStep, index) => {
        return {
            type: 'workflow',
            id: step.id,
            data: step,
            position: { x: 0, y: index * SEPARATION },
        }
    })
}

export const edgesToFlowEdges = (edges: AutomationEdge[]): Edge[] => {
    return edges.map((edge: AutomationEdge) => ({
        type: 'workflow',
        ...edge,
    }))
}

export const addPlaceholderFlowSteps = (flowSteps: Node[]) => {
    // TODO: add placeholder steps for all branches
    if (!flowSteps.length || flowSteps[flowSteps.length - 1].data.label !== AutomationStepKind.WebhookDestination) {
        return [
            ...flowSteps,
            {
                type: 'placeholder',
                id: uuid(),
                data: { label: 'placeholder' },
                position: { x: 0, y: flowSteps.length * SEPARATION },
            },
        ]
    }

    return flowSteps
}

export const addPlaceholderFlowEdges = (flowEdges: Edge[], flowSteps: Node[]) => {
    // TODO: add placeholder steps for all branches
    if (flowSteps.length > 1) {
        return [
            ...flowEdges,
            {
                type: 'placeholder',
                id: uuid(),
                source: flowSteps[flowSteps.length - 2].id,
                target: flowSteps[flowSteps.length - 1].id,
            },
        ]
    }

    return flowEdges
}
