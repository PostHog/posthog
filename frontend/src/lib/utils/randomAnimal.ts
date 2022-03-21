import { capitalizeFirstLetter, sampleOne } from '../utils'

// Adapted from poush/random-animal
const adjectives = [
    'furry',
    'amusing',
    'charming',
    'tame',
    'swift',
    'clever',
    'pleasant',
    'tiny',
    'wild',
    'herbivorous',
    'admirable',
    'adorable',
    'agile',
    'beautiful',
    'bossy',
    'candid',
    'cold',
    'colorful',
    'cuddly',
    'curious',
    'cute',
    'energetic',
    'fast',
    'feisty',
    'fierce',
    'fluffy',
    'friendly',
    'fuzzy',
    'grumpy',
    'hairy',
    'heavy',
    'large',
    'lazy',
    'loud',
    'lovable',
    'loving',
    'enchanted',
    'maternal',
    'sweet',
    'messy',
    'nocturnal',
    'noisy',
    'nosy',
    'picky',
    'playful',
    'quick',
    'sassy',
    'scaly',
    'short',
    'shy',
    'slow',
    'small',
    'smart',
    'soft',
    'strong',
    'tall',
    'tenacious',
    'glorious',
    'warm',
    'cheerful',
    'gracious',
]
const nouns = [
    'aardvark',
    'albatross',
    'alligator',
    'alpaca',
    'ant',
    'anteater',
    'antelope',
    'ape',
    'armadillo',
    'donkey',
    'baboon',
    'badger',
    'barracuda',
    'bat',
    'bear',
    'beaver',
    'bee',
    'bison',
    'boar',
    'buffalo',
    'butterfly',
    'camel',
    'capybara',
    'caribou',
    'cassowary',
    'cat',
    'caterpillar',
    'cattle',
    'chamois',
    'cheetah',
    'chicken',
    'chimpanzee',
    'chinchilla',
    'chough',
    'clam',
    'cobra',
    'cockroach',
    'cod',
    'cormorant',
    'coyote',
    'crab',
    'crane',
    'crocodile',
    'crow',
    'curlew',
    'deer',
    'dinosaur',
    'dog',
    'dogfish',
    'dolphin',
    'dotterel',
    'dove',
    'dragonfly',
    'duck',
    'dugong',
    'dunlin',
    'eagle',
    'echidna',
    'eel',
    'eland',
    'elephant',
    'elk',
    'emu',
    'falcon',
    'ferret',
    'finch',
    'firefox',
    'fish',
    'flamingo',
    'fly',
    'fox',
    'frog',
    'gaur',
    'gazelle',
    'gerbil',
    'giraffe',
    'gnat',
    'gnu',
    'goat',
    'goldfinch',
    'goldfish',
    'goose',
    'gorilla',
    'goshawk',
    'grasshopper',
    'grouse',
    'guanaco',
    'gull',
    'hamster',
    'hare',
    'hawk',
    'hedgehog',
    'heron',
    'herring',
    'hippopotamus',
    'hornet',
    'horse',
    'human',
    'hummingbird',
    'hyena',
    'ibex',
    'ibis',
    'jackal',
    'jaguar',
    'jay',
    'jellyfish',
    'kangaroo',
    'kingfisher',
    'koala',
    'kookabura',
    'kouprey',
    'kudu',
    'lapwing',
    'lark',
    'lemur',
    'leopard',
    'lion',
    'llama',
    'lobster',
    'locust',
    'loris',
    'louse',
    'lyrebird',
    'magpie',
    'mallard',
    'manatee',
    'mandrill',
    'mantis',
    'marten',
    'meerkat',
    'mink',
    'mole',
    'mongoose',
    'monkey',
    'moose',
    'mosquito',
    'mouse',
    'mule',
    'narwhal',
    'newt',
    'nightingale',
    'octopus',
    'okapi',
    'opossum',
    'oryx',
    'ostrich',
    'otter',
    'owl',
    'oyster',
    'panther',
    'parrot',
    'partridge',
    'peafowl',
    'pelican',
    'penguin',
    'pheasant',
    'pig',
    'pigeon',
    'pony',
    'porcupine',
    'porpoise',
    'quail',
    'quelea',
    'quetzal',
    'rabbit',
    'raccoon',
    'rail',
    'ram',
    'rat',
    'raven',
    'reindeer',
    'rhinoceros',
    'rook',
    'salamander',
    'salmon',
    'sandpiper',
    'sardine',
    'scorpion',
    'seahorse',
    'seal',
    'shark',
    'sheep',
    'shrew',
    'skunk',
    'snail',
    'snake',
    'sparrow',
    'spider',
    'spoonbill',
    'squid',
    'squirrel',
    'starling',
    'stingray',
    'stinkbug',
    'stork',
    'swallow',
    'swan',
    'tapir',
    'tarsier',
    'termite',
    'tiger',
    'toad',
    'trout',
    'turkey',
    'turtle',
    'viper',
    'vulture',
    'wallaby',
    'walrus',
    'wasp',
    'weasel',
    'whale',
    'wildcat',
    'wolf',
    'wolverine',
    'wombat',
    'woodcock',
    'woodpecker',
    'worm',
    'wren',
    'yak',
    'zebra',
]

/** Randomly return one of 18648 (84 * 222) animal adjective + noun combinations. */
export function generateRandomAnimal(): string {
    return `${capitalizeFirstLetter(sampleOne(adjectives))} ${capitalizeFirstLetter(sampleOne(nouns))}`
}
