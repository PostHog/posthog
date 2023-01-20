// Loads custom icons (some icons may come from a third-party library)
import { ImgHTMLAttributes } from 'react'
import surprisedHog from 'public/hedgehog/surprised-hog.png'
import xRayHog from 'public/hedgehog/x-ray-hog.png'
import hospitalHog from 'public/hedgehog/hospital-hog.png'
import blushingHog from 'public/hedgehog/blushing-hog.png'
import laptopHog1 from 'public/hedgehog/laptop-hog-01.png'
import laptopHog2 from 'public/hedgehog/laptop-hog-02.png'
import explorerHog from 'public/hedgehog/explorer-hog.png'
import runningHog from 'public/hedgehog/running-hog.png'
import spaceHog from 'public/hedgehog/space-hog.png'
import tronHog from 'public/hedgehog/tron-hog.png'
import heartHog from 'public/hedgehog/heart-hog.png'
import starHog from 'public/hedgehog/star-hog.png'
import policeHog from 'public/hedgehog/police-hog.png'
import sleepingHog from 'public/hedgehog/sleeping-hog.png'
import builderHog1 from 'public/hedgehog/builder-hog-01.png'
import builderHog2 from 'public/hedgehog/builder-hog-02.png'
import builderHog3 from 'public/hedgehog/builder-hog-03.png'
import professorHog from 'public/hedgehog/professor-hog.png'
import supportHeroHog from 'public/hedgehog/support-hero-hog.png'
import xRayHog2 from 'public/hedgehog/x-ray-hogs-02.png'
import laptopHog3 from 'public/hedgehog/laptop-hog-03.png'
import detectiveHog from 'public/hedgehog/detective-hog.png'

type HedgehogProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'>

// w400 x h400
const SquaredHedgehog = (props: ImgHTMLAttributes<HTMLImageElement>): JSX.Element => {
    return <img src={props.src} width={400} height={400} {...props} />
}
// any width x h400
const RectangularHedgehog = (props: ImgHTMLAttributes<HTMLImageElement>): JSX.Element => {
    return <img src={props.src} height={400} {...props} />
}

export const SurprisedHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={surprisedHog} {...props} />
}
export const XRayHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={xRayHog} {...props} />
}
export const XRayHog2 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={xRayHog2} {...props} />
}
export const HospitalHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={hospitalHog} {...props} />
}
export const BlushingHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={blushingHog} {...props} />
}
export const LaptopHog1 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={laptopHog1} {...props} />
}
export const LaptopHog2 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={laptopHog2} {...props} />
}
export const LaptopHog3 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={laptopHog3} {...props} />
}
export const ExplorerHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={explorerHog} {...props} />
}
export const RunningHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={runningHog} {...props} />
}
export const SpaceHog = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={spaceHog} {...props} />
}
export const TronHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={tronHog} {...props} />
}
export const HeartHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={heartHog} {...props} />
}
export const StarHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={starHog} {...props} />
}
export const PoliceHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={policeHog} {...props} />
}
export const SleepingHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={sleepingHog} {...props} />
}
export const BuilderHog1 = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={builderHog1} {...props} />
}
export const BuilderHog2 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={builderHog2} {...props} />
}
export const BuilderHog3 = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={builderHog3} {...props} />
}
export const ProfessorHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={professorHog} {...props} />
}
export const SupportHeroHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={supportHeroHog} {...props} />
}
export const DetectiveHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={detectiveHog} {...props} />
}
