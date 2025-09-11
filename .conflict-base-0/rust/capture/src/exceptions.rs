pub trait Exception {
    fn fingerprint(&self) -> String;
}

pub trait Stacked {
    type Frame;

    fn raw_ident(&self) -> String;
    fn stack(&self) -> Vec<Self::Frame>;
    fn lang_hint(&self) -> String;
}
