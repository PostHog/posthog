// Loads custom icons (some icons may come from a third-party library)
import { ImgHTMLAttributes } from 'react'

import bigLeaguesHog from 'public/hedgehog/big-leagues.png'
import blushingHog from 'public/hedgehog/blushing-hog.png'
import builderHog1 from 'public/hedgehog/builder-hog-01.png'
import builderHog2 from 'public/hedgehog/builder-hog-02.png'
import builderHog3 from 'public/hedgehog/builder-hog-03.png'
import burningMoneyHog from 'public/hedgehog/burning-money-hog.png'
import climberHog1 from 'public/hedgehog/climber-hog-01.png'
import climberHog2 from 'public/hedgehog/climber-hog-02.png'
import detectiveHog from 'public/hedgehog/detective-hog.png'
import experimentsHog from 'public/hedgehog/experiments-hog.png'
import explorerHog from 'public/hedgehog/explorer-hog.png'
import featureFlagHog from 'public/hedgehog/feature-flag-hog.png'
import filmCameraHog from 'public/hedgehog/filmcamera.png'
import heartHog from 'public/hedgehog/heart-hog.png'
import hospitalHog from 'public/hedgehog/hospital-hog.png'
import judgeHog from 'public/hedgehog/judge-hog.png'
import laptopHog1 from 'public/hedgehog/laptop-hog-01.png'
import laptopHog2 from 'public/hedgehog/laptop-hog-02.png'
import laptopHog3 from 'public/hedgehog/laptop-hog-03.png'
import laptopHog4 from 'public/hedgehog/laptop-hog-04.png'
import laptopHogEU from 'public/hedgehog/laptop-hog-eu.png'
import listHog from 'public/hedgehog/list-hog.png'
import mailHog from 'public/hedgehog/mail-hog.png'
import microphoneHog from 'public/hedgehog/microphone-hog.png'
import phonePairHogs from 'public/hedgehog/phone-pair-hogs.png'
import policeHog from 'public/hedgehog/police-hog.png'
import professorHog from 'public/hedgehog/professor-hog.png'
import readingHog from 'public/hedgehog/reading-hog.png'
import runningHog from 'public/hedgehog/running-hog.png'
import sleepingHog from 'public/hedgehog/sleeping-hog.png'
import spaceHog from 'public/hedgehog/space-hog.png'
import starHog from 'public/hedgehog/star-hog.png'
import supermanHog from 'public/hedgehog/superman-hog.png'
import supportHeroHog from 'public/hedgehog/support-hero-hog.png'
import surprisedHog from 'public/hedgehog/surprised-hog.png'
import tronHog from 'public/hedgehog/tron-hog.png'
import warningHog from 'public/hedgehog/warning-hog.png'
import wavingHog from 'public/hedgehog/waving-hog.png'
import xRayHog from 'public/hedgehog/x-ray-hog.png'
import xRayHog2 from 'public/hedgehog/x-ray-hogs-02.png'
import ycHog from 'public/hedgehog/yc-hog.png'

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
export const LaptopHog4 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={laptopHog4} {...props} />
}
export const LaptopHogEU = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={laptopHogEU} {...props} />
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
export const MailHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={mailHog} {...props} />
}
export const FeatureFlagHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={featureFlagHog} {...props} />
}
export const ExperimentsHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={experimentsHog} {...props} />
}
export const ListHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={listHog} {...props} />
}
export const WarningHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={warningHog} {...props} />
}
export const WavingHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={wavingHog} {...props} />
}
export const ReadingHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={readingHog} {...props} />
}
export const MicrophoneHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={microphoneHog} {...props} />
}
export const PhonePairHogs = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={phonePairHogs} {...props} />
}
export const BurningMoneyHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={burningMoneyHog} {...props} />
}
export const FilmCameraHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={filmCameraHog} {...props} />
}
export const SupermanHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={supermanHog} {...props} />
}
export const JudgeHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={judgeHog} {...props} />
}
export const ClimberHog1 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={climberHog1} width={378} height={417} {...props} />
}
export const ClimberHog2 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={climberHog2} width={518} height={1586} {...props} />
}
export const YCHog = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={ycHog} width={1134} height={651} {...props} />
}
export const BigLeaguesHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={bigLeaguesHog} {...props} />
}
