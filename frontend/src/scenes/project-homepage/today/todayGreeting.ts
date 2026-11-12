type Greeting = (name: string | null | undefined) => string

const withName =
    (text: string): Greeting =>
    (name) =>
        name ? `${text}, ${name}.` : `${text}.`
const plain =
    (text: string): Greeting =>
    () =>
        text

const LATE_NIGHT: Greeting[] = [
    withName('You’re up late'),
    plain('Chat, is this real?'),
    plain('U should go to sleep.'),
]
const EARLY_MORNING: Greeting[] = [plain('Riiiseee and shiiinee.'), plain('Good morning, sunshine.')]
const WEDNESDAY: Greeting[] = [plain('It’s Wednesday, my dudes.'), plain('Lemon, it’s Wednesday.')]
const FRIDAY_AFTERNOON: Greeting[] = [plain('Ladies and gentlemen, the weekend.'), plain('It’s Friday, Friday.')]
const WEEKEND: Greeting[] = [plain('Ladies and gentlemen, the weekend.'), withName('Working the weekend')]
const MONDAY_MORNING: Greeting[] = [withName('We are so back')]
const ANY_TIME: Greeting[] = [
    withName('We are so back'),
    plain('Chat, is this real?'),
    plain('Let them cook.'),
    plain('An elegant weapon for a more civilized age.'),
    plain('Big if true.'),
    plain('I ain’t reading all that.'),
    plain('I’m not arguing, I’m just explaining why I’m right.'),
    plain('Hi, welcome to Chili’s.'),
    plain('I basically run on iced data and panic.'),
    plain('Sir, this is a homepage.'),
    plain('Welcome back to the simulation.'),
    plain('Look at you, perceiving things.'),
    plain('Are we doing things today, or just looking at them?'),
    plain('You’re doing great. (Probably.)'),
    plain('Nice of u to show up again.'),
    withName('HELLOOO'),
    withName('Hiiii'),
    plain('Heyyy 💗'),
    plain('Look who it is.'),
]

function greetingPool(day: number, hour: number): Greeting[] {
    if (hour < 5) {
        return LATE_NIGHT
    }
    if (hour < 9) {
        return EARLY_MORNING
    }
    if (day === 0 || day === 6) {
        return WEEKEND
    }
    if (day === 3) {
        return WEDNESDAY
    }
    if (day === 5 && hour >= 12) {
        return FRIDAY_AFTERNOON
    }
    if (day === 1 && hour < 12) {
        return MONDAY_MORNING
    }
    return ANY_TIME
}

/** The index comes from the local date, so a line holds within a time band and can change at a band boundary. */
export function greetingFor(date: Date, name: string | null | undefined): string {
    const pool = greetingPool(date.getDay(), date.getHours())
    const dayIndex = Math.floor(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / (24 * 60 * 60 * 1000))
    return pool[dayIndex % pool.length](name)
}
